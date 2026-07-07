"""Confidence calibration and paper actionability diagnostics.

This module is deliberately read-only. It consumes current public V2 runtime
payloads, builds confidence/actionability artifacts, and never changes live or
paper runtime thresholds.
"""
from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.publisher import dumps_pretty


GO_READY = "V2_CONFIDENCE_CALIBRATION_AND_PAPER_ACTIONABILITY_IMPROVEMENT_READY"
GO_BLOCKED = "V2_CONFIDENCE_CALIBRATION_AND_PAPER_ACTIONABILITY_IMPROVEMENT_BLOCKED"
SCHEMA_VERSION = "v2_confidence_calibration_paper_actionability_v1"
ARTIFACT_REL = Path("v2_confidence_calibration_and_paper_actionability_improvement/latest")

PREDICTION_SOURCE_REL = Path(
    "operator_runtime/v2_signals/latest/all_symbol_all_timeframe_cuda_prediction_status.json"
)
RUNTIME_TRUTH_REL = Path("operator_runtime/v2_runtime_truth/latest/operator_runtime_truth.json")
PORTFOLIO_REL = Path("operator_runtime/v2_portfolio_state/latest/v2_portfolio_state.json")
OUTCOME_OBSERVER_REL = Path(
    "operator_runtime/paper_shadow_outcome_observer/latest/paper_shadow_outcome_observer_status.json"
)
EXPLANATION_REL = Path(
    "operator_runtime/v2_prediction_signal_explanations/latest/prediction_signal_explanations.json"
)
PAPER_FEEDBACK_REL = Path(
    "operator_runtime/v2_paper_trade_management/latest/trainer_feedback_outcomes.json"
)
BUCKET_QUARANTINE_REL = Path(
    "operator_runtime/v2_paper_trade_management/latest/bucket_quarantine_status.json"
)

CONFIDENCE_BUCKETS = (
    (0.50, 0.52),
    (0.52, 0.53),
    (0.53, 0.54),
    (0.54, 0.545),
    (0.545, 0.55),
    (0.55, 0.555),
    (0.555, 0.60),
    (0.60, 1.01),
)

SIMULATION_THRESHOLDS = (0.55, 0.545, 0.54, 0.535, 0.53, 0.525, 0.52)


@dataclass(frozen=True)
class ConfidenceActionabilityPaths:
    repo_root: Path
    worklog_dir: Path
    public_dir: Path
    prediction_source_path: Path
    runtime_truth_path: Path
    portfolio_path: Path
    outcome_observer_path: Path
    explanation_path: Path
    paper_feedback_path: Path
    bucket_quarantine_path: Path


@dataclass(frozen=True)
class ConfidenceActionabilityResult:
    go_no_go: str
    artifacts: dict[str, Any]
    operator_dashboard_payload: dict[str, Any]
    paths_written: tuple[str, ...] = field(default_factory=tuple)


def default_paths(repo_root: Path) -> ConfidenceActionabilityPaths:
    root = repo_root.resolve()
    public_root = root / "v2/frontend/public"
    return ConfidenceActionabilityPaths(
        repo_root=root,
        worklog_dir=root / "claude_worklog/final_readiness" / ARTIFACT_REL,
        public_dir=public_root / ARTIFACT_REL,
        prediction_source_path=public_root / PREDICTION_SOURCE_REL,
        runtime_truth_path=public_root / RUNTIME_TRUTH_REL,
        portfolio_path=public_root / PORTFOLIO_REL,
        outcome_observer_path=public_root / OUTCOME_OBSERVER_REL,
        explanation_path=public_root / EXPLANATION_REL,
        paper_feedback_path=public_root / PAPER_FEEDBACK_REL,
        bucket_quarantine_path=public_root / BUCKET_QUARANTINE_REL,
    )


def _est_iso() -> str:
    return datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _bool(value: Any) -> bool:
    return bool(value) if isinstance(value, bool) else str(value).lower() == "true"


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None, "median": None}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": _mean(values),
        "median": _median(values),
    }


def _bucket(confidence: float | None) -> str:
    if confidence is None:
        return "missing"
    for low, high in CONFIDENCE_BUCKETS:
        if low <= confidence < high:
            return f"{low:.3f}-{high:.3f}"
    if confidence < CONFIDENCE_BUCKETS[0][0]:
        return f"below-{CONFIDENCE_BUCKETS[0][0]:.3f}"
    return f"{CONFIDENCE_BUCKETS[-1][1]:.3f}-plus"


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _known_bucket_value(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text) and text.upper() != "UNKNOWN"


def _row_side(row: Mapping[str, Any]) -> str:
    return str(
        _first_present(row.get("selected_action"), row.get("action"), row.get("side"))
        or "UNKNOWN"
    ).lower()


def _row_regime(row: Mapping[str, Any]) -> str:
    return str(
        _first_present(
            row.get("market_regime"),
            row.get("market_regime_at_entry"),
            row.get("strategy_market_regime"),
        )
        or "UNKNOWN"
    )


def _row_strategy(row: Mapping[str, Any]) -> str:
    return str(
        _first_present(
            row.get("strategy_mode"),
            row.get("strategy_canonical_mode"),
            row.get("strategy_id"),
            row.get("strategy_family"),
            row.get("strategy_subtype"),
            row.get("strategy_selected_mode"),
            row.get("strategy_router_selected_mode"),
        )
        or "UNKNOWN"
    )


def _loss_quarantine_candidate_keys(row: Mapping[str, Any]) -> set[str]:
    symbol = str(row.get("symbol") or "UNKNOWN").upper()
    timeframe = str(row.get("timeframe") or "UNKNOWN")
    side = _row_side(row)
    strategy = _row_strategy(row)
    regime = _row_regime(row)
    confidence_bucket = _bucket(_float(row.get("confidence_calibrated")))
    keys = {f"{symbol}|{timeframe}|{strategy}|{regime}"}
    if _known_bucket_value(side):
        keys.add(f"side:{side}")
    if _known_bucket_value(regime):
        keys.add(f"regime:{regime}")
    if _known_bucket_value(timeframe):
        keys.add(f"timeframe:{timeframe}")
    if _known_bucket_value(strategy) and _known_bucket_value(regime):
        keys.add(f"strategy_regime:{strategy}|{regime}")
    if _known_bucket_value(confidence_bucket) and _known_bucket_value(regime):
        keys.add(f"confidence_regime:{confidence_bucket}|{regime}")
    return keys


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return _as_dict(json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError:
        return {}


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    tmp.replace(path)


def _prediction_rows(source: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [_as_dict(row) for row in _as_list(source.get("prediction_rows"))]


def _block_reasons(row: Mapping[str, Any]) -> list[str]:
    return [str(reason) for reason in _as_list(row.get("paper_fill_gate_block_reasons"))]


def _action(row: Mapping[str, Any]) -> str:
    return str(row.get("selected_action") or "unknown").lower()


def _is_paper_allowed(row: Mapping[str, Any]) -> bool:
    return _bool(row.get("paper_fill_allowed"))


def _valid_paper_shape(row: Mapping[str, Any]) -> bool:
    expected = _float(row.get("expected_move_after_cost_bps"))
    confidence = _float(row.get("confidence_calibrated"))
    integrity = _float(row.get("market_state_integrity_score"))
    coverage = _float(row.get("data_coverage_percent"))
    stale = int(_float(row.get("stale_feature_count")) or 0)
    price_status = str(row.get("price_target_validation_status") or "").upper()
    return (
        _bool(row.get("valid_for_paper"))
        and _bool(row.get("valid_for_training"))
        and _action(row) in {"long", "short"}
        and confidence is not None
        and expected is not None
        and expected >= 8.0
        and (integrity is None or integrity >= 90.0)
        and (coverage is None or coverage >= 70.0)
        and stale == 0
        and price_status in {"", "VALID"}
    )


def _is_under_confident_candidate(row: Mapping[str, Any]) -> bool:
    return (
        not _is_paper_allowed(row)
        and "confidence_below_threshold" in _block_reasons(row)
        and _valid_paper_shape(row)
    )


def _weak_reasons(row: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    expected = _float(row.get("expected_move_after_cost_bps"))
    confidence = _float(row.get("confidence_calibrated"))
    integrity = _float(row.get("market_state_integrity_score"))
    coverage = _float(row.get("data_coverage_percent"))
    stale = int(_float(row.get("stale_feature_count")) or 0)
    missing = int(_float(row.get("missing_feature_count")) or 0)
    price_status = str(row.get("price_target_validation_status") or "").upper()

    if not _bool(row.get("valid_for_paper")):
        reasons.append("invalid_for_paper")
    if not _bool(row.get("valid_for_training")):
        reasons.append("invalid_for_training")
    if _action(row) not in {"long", "short"}:
        reasons.append("non_trade_action")
    if confidence is None:
        reasons.append("confidence_missing")
    if expected is None:
        reasons.append("expected_move_after_cost_missing")
    elif expected < 8.0:
        reasons.append("expected_move_after_cost_below_paper_experiment_min")
    if integrity is not None and integrity < 90.0:
        reasons.append("market_state_integrity_below_90")
    if coverage is not None and coverage < 70.0:
        reasons.append("data_coverage_below_70")
    if stale > 0:
        reasons.append("stale_feature_present")
    if missing > 45:
        reasons.append("too_many_missing_features")
    if price_status not in {"", "VALID"}:
        reasons.append("price_target_not_valid")
    return reasons


def _counter(rows: list[Mapping[str, Any]], field: str) -> dict[str, int]:
    counts = Counter(str(row.get(field) or "unknown") for row in rows)
    return dict(sorted(counts.items()))


def build_confidence_gate_block_distribution(
    predictions: list[dict[str, Any]],
    *,
    generated_est: str,
    source_generated_est: str | None,
) -> dict[str, Any]:
    block_counts: Counter[str] = Counter()
    for row in predictions:
        block_counts.update(_block_reasons(row))

    allowed = [row for row in predictions if _is_paper_allowed(row)]
    blocked = [row for row in predictions if not _is_paper_allowed(row)]
    confidence_values = [_float(row.get("confidence_calibrated")) for row in predictions]
    expected_values = [_float(row.get("expected_move_after_cost_bps")) for row in predictions]

    by_bucket: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "prediction_count": 0,
            "paper_allowed_count": 0,
            "confidence_blocked_count": 0,
            "positive_expected_after_cost_count": 0,
            "avg_expected_move_after_cost_bps": None,
            "_expected": [],
        }
    )
    for row in predictions:
        bucket = _bucket(_float(row.get("confidence_calibrated")))
        item = by_bucket[bucket]
        item["prediction_count"] += 1
        item["paper_allowed_count"] += int(_is_paper_allowed(row))
        item["confidence_blocked_count"] += int("confidence_below_threshold" in _block_reasons(row))
        expected = _float(row.get("expected_move_after_cost_bps"))
        if expected is not None:
            item["_expected"].append(expected)
            item["positive_expected_after_cost_count"] += int(expected > 0.0)
    for item in by_bucket.values():
        item["avg_expected_move_after_cost_bps"] = _mean(item.pop("_expected"))

    return {
        "schema_version": f"{SCHEMA_VERSION}_gate_distribution",
        "generated_est": generated_est,
        "prediction_payload_generated_est": source_generated_est,
        "total_prediction_rows": len(predictions),
        "paper_fill_allowed_prediction_rows": len(allowed),
        "paper_blocked_prediction_rows": len(blocked),
        "block_reason_counts": dict(block_counts.most_common()),
        "selected_action_counts": _counter(predictions, "selected_action"),
        "timeframe_counts": _counter(predictions, "timeframe"),
        "confidence_stats": {
            "all": _stats([value for value in confidence_values if value is not None]),
            "paper_allowed": _stats(
                [value for value in (_float(row.get("confidence_calibrated")) for row in allowed) if value is not None]
            ),
            "paper_blocked": _stats(
                [value for value in (_float(row.get("confidence_calibrated")) for row in blocked) if value is not None]
            ),
        },
        "expected_move_after_cost_stats": {
            "all": _stats([value for value in expected_values if value is not None]),
            "paper_allowed": _stats(
                [value for value in (_float(row.get("expected_move_after_cost_bps")) for row in allowed) if value is not None]
            ),
            "paper_blocked": _stats(
                [value for value in (_float(row.get("expected_move_after_cost_bps")) for row in blocked) if value is not None]
            ),
        },
        "by_confidence_bucket": dict(sorted(by_bucket.items())),
    }


def _outcome_rows(outcome_source: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [_as_dict(row) for row in _as_list(outcome_source.get("observations"))]


def _portfolio_prediction_ids(portfolio: Mapping[str, Any]) -> set[str]:
    ids: set[str] = set()
    for position in _as_list(portfolio.get("positions_by_symbol")):
        for fill_id in _as_list(_as_dict(position).get("source_fill_ids")):
            if isinstance(fill_id, str) and fill_id.startswith("v2h_"):
                ids.add(fill_id)
    return ids


def build_confidence_bucket_outcome_analysis(
    predictions: list[dict[str, Any]],
    outcome_source: Mapping[str, Any],
    portfolio: Mapping[str, Any],
    *,
    generated_est: str,
) -> dict[str, Any]:
    observations = _outcome_rows(outcome_source)
    observations_by_prediction = {
        str(row.get("prediction_id")): row for row in observations if row.get("prediction_id")
    }
    accepted_prediction_ids = _portfolio_prediction_ids(portfolio)

    bucket_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in predictions:
        bucket_rows[_bucket(_float(row.get("confidence_calibrated")))].append(row)

    bucket_analysis: list[dict[str, Any]] = []
    total_matched_observations = 0
    total_matched_portfolio = 0
    for bucket, rows in sorted(bucket_rows.items()):
        matched = [observations_by_prediction[str(row.get("prediction_id"))] for row in rows if str(row.get("prediction_id")) in observations_by_prediction]
        portfolio_matches = [row for row in rows if str(row.get("prediction_id")) in accepted_prediction_ids]
        total_matched_observations += len(matched)
        total_matched_portfolio += len(portfolio_matches)
        expected = [_float(row.get("expected_move_after_cost_bps")) for row in rows]
        mfe = [_float(row.get("max_favorable_excursion_bps")) for row in matched]
        mae = [_float(row.get("max_adverse_excursion_bps")) for row in matched]
        after_cost_correct = [row for row in matched if _bool(row.get("after_cost_correct"))]
        no_trade_correct = [row for row in matched if _bool(row.get("no_trade_correct"))]
        bucket_analysis.append(
            {
                "confidence_bucket": bucket,
                "prediction_count": len(rows),
                "paper_allowed_count": sum(1 for row in rows if _is_paper_allowed(row)),
                "confidence_blocked_count": sum(
                    1 for row in rows if "confidence_below_threshold" in _block_reasons(row)
                ),
                "positive_expected_after_cost_count": sum(
                    1 for value in expected if value is not None and value > 0.0
                ),
                "avg_expected_move_after_cost_bps": _mean([value for value in expected if value is not None]),
                "matched_shadow_outcome_count": len(matched),
                "matched_portfolio_fill_count": len(portfolio_matches),
                "after_cost_correct_count": len(after_cost_correct),
                "no_trade_correct_count": len(no_trade_correct),
                "avg_max_favorable_excursion_bps": _mean([value for value in mfe if value is not None]),
                "avg_max_adverse_excursion_bps": _mean([value for value in mae if value is not None]),
            }
        )

    completed = [row for row in observations if _bool(row.get("completed"))]
    return {
        "schema_version": f"{SCHEMA_VERSION}_bucket_outcomes",
        "generated_est": generated_est,
        "prediction_rows": len(predictions),
        "shadow_observations_total": outcome_source.get("observations_total", len(observations)),
        "shadow_completed_observations": outcome_source.get("completed_observations", len(completed)),
        "matched_current_prediction_outcomes": total_matched_observations,
        "matched_current_portfolio_prediction_fills": total_matched_portfolio,
        "outcome_join_status": (
            "JOINED_BY_PREDICTION_ID"
            if total_matched_observations
            else "NO_CURRENT_PREDICTION_OUTCOME_MATCHES_YET"
        ),
        "portfolio_join_status": (
            "JOINED_CURRENT_PORTFOLIO_SOURCE_FILL_IDS"
            if total_matched_portfolio
            else "NO_CURRENT_PORTFOLIO_FILL_MATCHES_CURRENT_PREDICTION_GRID"
        ),
        "bucket_analysis": bucket_analysis,
        "shadow_outcome_summary_without_confidence_bucket": {
            "completed_observations": len(completed),
            "false_block_reason_counts": outcome_source.get("false_block_reason_counts", {}),
            "no_trade_correct_count": sum(1 for row in completed if _bool(row.get("no_trade_correct"))),
            "would_have_beaten_costs_count": sum(1 for row in completed if _bool(row.get("would_have_beaten_costs"))),
            "avg_completed_max_favorable_excursion_bps": _mean(
                [value for value in (_float(row.get("max_favorable_excursion_bps")) for row in completed) if value is not None]
            ),
            "avg_completed_max_adverse_excursion_bps": _mean(
                [value for value in (_float(row.get("max_adverse_excursion_bps")) for row in completed) if value is not None]
            ),
        },
    }


def build_paper_actionability_candidate_recovery(
    predictions: list[dict[str, Any]],
    *,
    generated_est: str,
    blocked_bucket_keys: set[str] | None = None,
) -> dict[str, Any]:
    blocked_bucket_keys = blocked_bucket_keys or set()
    under_confident = [row for row in predictions if _is_under_confident_candidate(row)]
    loss_quarantined_under_confident = [
        row
        for row in under_confident
        if _loss_quarantine_candidate_keys(row) & blocked_bucket_keys
    ]
    under_confident_after_loss_adjustment = [
        row
        for row in under_confident
        if not (_loss_quarantine_candidate_keys(row) & blocked_bucket_keys)
    ]
    weak_rows = [row for row in predictions if not _is_paper_allowed(row) and not _is_under_confident_candidate(row)]
    weak_reason_counts = Counter(reason for row in weak_rows for reason in _weak_reasons(row))

    ranked = sorted(
        under_confident_after_loss_adjustment,
        key=lambda row: (
            _float(row.get("expected_move_after_cost_bps")) or -9999.0,
            _float(row.get("confidence_calibrated")) or 0.0,
            _float(row.get("market_state_integrity_score")) or 0.0,
        ),
        reverse=True,
    )
    sample = [
        {
            "prediction_id": row.get("prediction_id"),
            "symbol": row.get("symbol"),
            "timeframe": row.get("timeframe"),
            "selected_action": row.get("selected_action"),
            "confidence_calibrated": row.get("confidence_calibrated"),
            "expected_move_after_cost_bps": row.get("expected_move_after_cost_bps"),
            "market_state_integrity_score": row.get("market_state_integrity_score"),
            "data_coverage_percent": row.get("data_coverage_percent"),
            "paper_fill_gate_block_reasons": _block_reasons(row),
            "recovery_classification": "UNDER_CONFIDENT_PAPER_ONLY_CANDIDATE",
            "allowed_scope": "paper_simulation_only",
            "loss_quarantine_matched_bucket_keys": sorted(
                _loss_quarantine_candidate_keys(row) & blocked_bucket_keys
            ),
        }
        for row in ranked[:100]
    ]

    return {
        "schema_version": f"{SCHEMA_VERSION}_candidate_recovery",
        "generated_est": generated_est,
        "prediction_rows": len(predictions),
        "paper_fill_allowed_before": sum(1 for row in predictions if _is_paper_allowed(row)),
        "confidence_blocked_rows": sum(
            1 for row in predictions if "confidence_below_threshold" in _block_reasons(row)
        ),
        "under_confident_candidate_count": len(under_confident),
        "loss_quarantine_filtered_under_confident_candidate_count": len(
            loss_quarantined_under_confident
        ),
        "actionable_after_loss_adjustment_candidate_count": len(
            under_confident_after_loss_adjustment
        ),
        "active_loss_quarantine_bucket_keys": sorted(blocked_bucket_keys),
        "genuinely_weak_or_invalid_block_count": len(weak_rows),
        "weak_or_invalid_reason_counts": dict(weak_reason_counts.most_common()),
        "candidate_rows_sample": sample,
        "action": "SIMULATE_PAPER_ONLY_THRESHOLD_CHANGE_DO_NOT_APPLY_TO_LIVE",
        "live_threshold_changed": False,
        "paper_threshold_changed": False,
    }


def _paper_feedback_rows(source: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = source.get("trainer_feedback_outcomes")
    if isinstance(rows, list):
        return [_as_dict(row) for row in rows]
    return []


def build_loss_adjusted_paper_actionability_status(
    predictions: list[dict[str, Any]],
    paper_feedback_payload: Mapping[str, Any],
    bucket_quarantine_status: Mapping[str, Any],
    *,
    generated_est: str,
) -> dict[str, Any]:
    blocked_bucket_keys = {
        str(key)
        for key in _as_list(bucket_quarantine_status.get("blocked_bucket_keys"))
        if str(key)
    }
    feedback_rows = _paper_feedback_rows(paper_feedback_payload)
    matched_prediction_rows: list[dict[str, Any]] = []
    matched_under_confident_count = 0
    for row in predictions:
        matched = sorted(_loss_quarantine_candidate_keys(row) & blocked_bucket_keys)
        if not matched:
            continue
        matched_under_confident_count += int(_is_under_confident_candidate(row))
        matched_prediction_rows.append(
            {
                "prediction_id": row.get("prediction_id"),
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "selected_action": row.get("selected_action"),
                "confidence_calibrated": row.get("confidence_calibrated"),
                "expected_move_after_cost_bps": row.get(
                    "expected_move_after_cost_bps"
                ),
                "paper_fill_allowed_before_loss_adjustment": _is_paper_allowed(row),
                "paper_actionability_after_loss_adjustment": False,
                "loss_adjustment_reason": "CURRENT_PAPER_LOSS_BUCKET_QUARANTINE",
                "matched_loss_quarantine_bucket_keys": matched,
            }
        )
    high_confidence_feedback_losses = [
        row
        for row in feedback_rows
        if (_float(row.get("confidence_calibrated")) or 0.0) >= 0.55
        and row.get("action_was_profitable") is False
    ]
    return {
        "schema_version": f"{SCHEMA_VERSION}_loss_adjusted_actionability",
        "generated_est": generated_est,
        "status": (
            "LOSS_ADJUSTED_ACTIONABILITY_ACTIVE"
            if blocked_bucket_keys
            else "NO_ACTIVE_LOSS_QUARANTINE_KEYS"
        ),
        "paper_only": True,
        "runtime_thresholds_changed": False,
        "paper_threshold_changed": False,
        "live_threshold_changed": False,
        "live_risk_changed": False,
        "paper_feedback_generated_utc": paper_feedback_payload.get("generated_utc"),
        "bucket_quarantine_generated_utc": bucket_quarantine_status.get(
            "generated_utc"
        ),
        "bucket_quarantine_status": bucket_quarantine_status.get("status"),
        "active_loss_quarantine_bucket_keys": sorted(blocked_bucket_keys),
        "active_loss_quarantine_bucket_key_count": len(blocked_bucket_keys),
        "paper_feedback_outcome_rows": len(feedback_rows),
        "high_confidence_feedback_loss_rows": len(high_confidence_feedback_losses),
        "loss_adjusted_prediction_count": len(matched_prediction_rows),
        "loss_adjusted_under_confident_candidate_count": matched_under_confident_count,
        "sample_loss_adjusted_predictions": matched_prediction_rows[:100],
    }


def _passes_threshold_simulation(row: Mapping[str, Any], threshold: float) -> bool:
    confidence = _float(row.get("confidence_calibrated"))
    return confidence is not None and confidence >= threshold and _valid_paper_shape(row)


def build_paper_only_threshold_simulation(
    predictions: list[dict[str, Any]],
    *,
    generated_est: str,
) -> dict[str, Any]:
    current_allowed = {str(row.get("prediction_id")) for row in predictions if _is_paper_allowed(row)}
    simulations: list[dict[str, Any]] = []
    for threshold in SIMULATION_THRESHOLDS:
        rows = [row for row in predictions if _passes_threshold_simulation(row, threshold)]
        row_ids = {str(row.get("prediction_id")) for row in rows}
        recovered = [row for row in rows if str(row.get("prediction_id")) not in current_allowed]
        simulations.append(
            {
                "paper_confidence_threshold": threshold,
                "simulated_paper_candidate_count": len(rows),
                "current_allowed_overlap": len(row_ids & current_allowed),
                "additional_recovered_candidate_count": len(recovered),
                "avg_expected_move_after_cost_bps": _mean(
                    [
                        value
                        for value in (_float(row.get("expected_move_after_cost_bps")) for row in rows)
                        if value is not None
                    ]
                ),
                "min_market_state_integrity_score": (
                    min(
                        value
                        for value in (
                            _float(row.get("market_state_integrity_score")) for row in rows
                        )
                        if value is not None
                    )
                    if rows
                    else None
                ),
                "runtime_thresholds_changed": False,
                "live_threshold_changed": False,
                "scope": "paper_only_simulation",
            }
        )
    return {
        "schema_version": f"{SCHEMA_VERSION}_threshold_simulation",
        "generated_est": generated_est,
        "status": "PAPER_ONLY_SIMULATION_READY",
        "current_inferred_paper_confidence_threshold": min(
            (
                _float(row.get("confidence_calibrated"))
                for row in predictions
                if _is_paper_allowed(row) and _float(row.get("confidence_calibrated")) is not None
            ),
            default=None,
        ),
        "simulation_thresholds": list(SIMULATION_THRESHOLDS),
        "simulations": simulations,
        "runtime_thresholds_changed": False,
        "paper_threshold_auto_applied": False,
        "live_threshold_changed": False,
        "live_risk_changed": False,
    }


def build_calibrated_confidence_threshold_proposal(
    distribution: Mapping[str, Any],
    outcome_analysis: Mapping[str, Any],
    simulation: Mapping[str, Any],
    *,
    generated_est: str,
) -> dict[str, Any]:
    confidence_stats = _as_dict(distribution.get("confidence_stats"))
    expected_stats = _as_dict(distribution.get("expected_move_after_cost_stats"))
    allowed_stats = _as_dict(confidence_stats.get("paper_allowed"))
    blocked_stats = _as_dict(confidence_stats.get("paper_blocked"))
    allowed_expected_stats = _as_dict(expected_stats.get("paper_allowed"))
    sims = _as_list(simulation.get("simulations"))
    preferred = next(
        (
            _as_dict(item)
            for item in sims
            if _float(_as_dict(item).get("paper_confidence_threshold")) == 0.54
        ),
        _as_dict(sims[0]) if sims else {},
    )
    shadow_summary = _as_dict(outcome_analysis.get("shadow_outcome_summary_without_confidence_bucket"))
    no_trade_correct = int(_float(shadow_summary.get("no_trade_correct_count")) or 0)
    completed = int(_float(shadow_summary.get("completed_observations")) or 0)
    status = (
        "PAPER_ONLY_TRIAL_PROPOSED_NEEDS_MONITOR"
        if completed >= 25
        else "PAPER_ONLY_TRIAL_BLOCKED_NEEDS_MORE_OUTCOME_EVIDENCE"
    )
    return {
        "schema_version": f"{SCHEMA_VERSION}_threshold_proposal",
        "generated_est": generated_est,
        "status": status,
        "live_threshold_change": "NO_CHANGE",
        "paper_runtime_threshold_change": "NO_AUTO_CHANGE",
        "current_inferred_paper_min_allowed_confidence": allowed_stats.get("min"),
        "max_confidence_still_blocked": blocked_stats.get("max"),
        "confidence_distribution_diagnosis": (
            "confidence_head_compressed_between_roughly_50_and_55_percent"
        ),
        "recommended_paper_only_trial": {
            "enabled": status == "PAPER_ONLY_TRIAL_PROPOSED_NEEDS_MONITOR",
            "paper_confidence_threshold": preferred.get("paper_confidence_threshold"),
            "expected_move_after_cost_floor_bps": 8.0,
            "market_state_integrity_floor": 90.0,
            "data_coverage_floor": 70.0,
            "stale_feature_count_required": 0,
            "additional_recovered_candidate_count": preferred.get("additional_recovered_candidate_count"),
            "monitor_window_minutes": 60,
            "operator_acceptance_required": True,
        },
        "why_no_live_change": [
            "live submit is balance-held",
            "paper-only evidence is still being accumulated",
            "confidence calibration changes must not lower live risk gates",
        ],
        "outcome_caution": {
            "completed_shadow_observations": completed,
            "no_trade_correct_count": no_trade_correct,
            "no_trade_correct_rate": (no_trade_correct / completed) if completed else None,
            "current_paper_allowed_expected_move_after_cost_mean_bps": allowed_expected_stats.get(
                "mean"
            ),
            "current_paper_allowed_expected_move_warning": (
                "current paper-allowed rows include weak or negative after-cost expected move, "
                "so any confidence experiment must keep the positive-edge filter"
            ),
            "interpretation": (
                "many low-confidence denials were correct, so use a guarded paper-only trial instead of a broad threshold drop"
            ),
        },
    }


def build_post_calibration_paper_monitor_status(
    runtime_truth: Mapping[str, Any],
    portfolio: Mapping[str, Any],
    *,
    generated_est: str,
) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}_post_monitor",
        "generated_est": generated_est,
        "status": "POST_CALIBRATION_MONITOR_ARMED_NO_RUNTIME_THRESHOLD_CHANGE",
        "paper_threshold_changed": False,
        "live_threshold_changed": False,
        "monitor_window_minutes": 60,
        "current_paper": {
            "accepted_fill_total": portfolio.get("accepted_fill_total")
            or runtime_truth.get("paper_accepted_fills"),
            "economic_fill_total": portfolio.get("economic_fill_total"),
            "open_positions_count": portfolio.get("open_positions_count")
            or runtime_truth.get("paper_open_positions_count"),
            "current_session_equity": portfolio.get("equity") or runtime_truth.get("paper_equity"),
            "current_session_pnl": portfolio.get("total_pnl_usd") or runtime_truth.get("paper_pnl"),
            "realized_pnl_usd": portfolio.get("realized_pnl_usd")
            or runtime_truth.get("paper_realized_pnl_usd"),
            "unrealized_pnl_usd": portfolio.get("unrealized_pnl_usd")
            or runtime_truth.get("paper_unrealized_pnl_usd"),
            "last_equity_update_est": portfolio.get("last_equity_update_est"),
        },
        "live_state": {
            "live_gate": runtime_truth.get("live_gate"),
            "trader_state": runtime_truth.get("trader_state"),
            "live_order_submit_allowed": runtime_truth.get("live_order_submit_allowed"),
            "live_order_submit_blocker": runtime_truth.get("live_order_submit_blocker"),
        },
        "alerts_to_emit_if_trial_accepted": [
            "PAPER_CONFIDENCE_TRIAL_DRAWDOWN_EXCEEDED",
            "PAPER_CONFIDENCE_TRIAL_ALLOWED_LOSER_RATE_HIGH",
            "PAPER_CONFIDENCE_TRIAL_NO_EDGE_AFTER_60M",
        ],
    }


def build_operator_dashboard_payload(
    artifacts: Mapping[str, Any],
    runtime_truth: Mapping[str, Any],
    portfolio: Mapping[str, Any],
    *,
    generated_est: str,
    go_no_go: str,
) -> dict[str, Any]:
    distribution = _as_dict(artifacts.get("confidence_gate_block_distribution.json"))
    recovery = _as_dict(artifacts.get("paper_actionability_candidate_recovery.json"))
    proposal = _as_dict(artifacts.get("calibrated_confidence_threshold_proposal.json"))
    simulation = _as_dict(artifacts.get("paper_only_threshold_simulation.json"))
    loss_adjusted = _as_dict(
        artifacts.get("loss_adjusted_paper_actionability_status.json")
    )
    current_simulation = next(
        (
            _as_dict(item)
            for item in _as_list(simulation.get("simulations"))
            if _float(_as_dict(item).get("paper_confidence_threshold")) == 0.55
        ),
        {},
    )
    return {
        "schema_version": f"{SCHEMA_VERSION}_operator_dashboard",
        "gate": go_no_go,
        "generated_est": generated_est,
        "status": "CONFIDENCE_CALIBRATION_ANALYSIS_READY",
        "summary": {
            "prediction_rows": distribution.get("total_prediction_rows"),
            "paper_fill_allowed_prediction_rows": distribution.get("paper_fill_allowed_prediction_rows"),
            "confidence_blocked_rows": _as_dict(distribution.get("block_reason_counts")).get(
                "confidence_below_threshold"
            ),
            "under_confident_candidate_count": recovery.get("under_confident_candidate_count"),
            "actionable_after_loss_adjustment_candidate_count": recovery.get(
                "actionable_after_loss_adjustment_candidate_count"
            ),
            "loss_quarantine_filtered_under_confident_candidate_count": recovery.get(
                "loss_quarantine_filtered_under_confident_candidate_count"
            ),
            "loss_adjusted_prediction_count": loss_adjusted.get(
                "loss_adjusted_prediction_count"
            ),
            "recommended_paper_only_threshold": _as_dict(
                proposal.get("recommended_paper_only_trial")
            ).get("paper_confidence_threshold"),
            "current_allowed_clean_positive_edge_overlap": current_simulation.get(
                "current_allowed_overlap"
            ),
            "paper_threshold_auto_applied": False,
            "live_threshold_changed": False,
        },
        "paper": {
            "accepted_fill_total": portfolio.get("accepted_fill_total")
            or runtime_truth.get("paper_accepted_fills"),
            "open_positions_count": portfolio.get("open_positions_count")
            or runtime_truth.get("paper_open_positions_count"),
            "equity": portfolio.get("equity") or runtime_truth.get("paper_equity"),
            "pnl": portfolio.get("total_pnl_usd") or runtime_truth.get("paper_pnl"),
        },
        "live": {
            "live_gate": runtime_truth.get("live_gate"),
            "trader_state": runtime_truth.get("trader_state"),
            "live_order_submit_allowed": runtime_truth.get("live_order_submit_allowed"),
            "live_order_submit_blocker": runtime_truth.get("live_order_submit_blocker"),
            "live_change": "NO_CHANGE",
        },
        "operator_next_action": (
            "Review the paper-only threshold trial proposal; do not apply to live."
        ),
        "safety": {
            "exchange_order_submitted": False,
            "test_order_called": False,
            "leverage_or_margin_mutation": False,
            "old_redis_write": False,
            "raw_credentials_exposed": False,
            "live_threshold_changed": False,
        },
    }


def build_confidence_actionability(
    *,
    prediction_source: Mapping[str, Any],
    runtime_truth: Mapping[str, Any],
    portfolio: Mapping[str, Any],
    outcome_observer: Mapping[str, Any],
    explanation_payload: Mapping[str, Any],
    generated_est: str,
    paper_feedback_payload: Mapping[str, Any] | None = None,
    bucket_quarantine_status: Mapping[str, Any] | None = None,
) -> ConfidenceActionabilityResult:
    predictions = _prediction_rows(prediction_source)
    paper_feedback_payload = _as_dict(paper_feedback_payload)
    bucket_quarantine_status = _as_dict(bucket_quarantine_status)
    blocked_bucket_keys = {
        str(key)
        for key in _as_list(bucket_quarantine_status.get("blocked_bucket_keys"))
        if str(key)
    }
    distribution = build_confidence_gate_block_distribution(
        predictions,
        generated_est=generated_est,
        source_generated_est=prediction_source.get("generated_est"),
    )
    outcome_analysis = build_confidence_bucket_outcome_analysis(
        predictions,
        outcome_observer,
        portfolio,
        generated_est=generated_est,
    )
    recovery = build_paper_actionability_candidate_recovery(
        predictions,
        generated_est=generated_est,
        blocked_bucket_keys=blocked_bucket_keys,
    )
    loss_adjusted = build_loss_adjusted_paper_actionability_status(
        predictions,
        paper_feedback_payload,
        bucket_quarantine_status,
        generated_est=generated_est,
    )
    simulation = build_paper_only_threshold_simulation(predictions, generated_est=generated_est)
    proposal = build_calibrated_confidence_threshold_proposal(
        distribution,
        outcome_analysis,
        simulation,
        generated_est=generated_est,
    )
    monitor = build_post_calibration_paper_monitor_status(
        runtime_truth,
        portfolio,
        generated_est=generated_est,
    )

    explanation_summary = _as_dict(explanation_payload.get("summary"))
    blockers: list[str] = []
    if not predictions:
        blockers.append("NO_CURRENT_NATIVE_CUDA_PREDICTION_ROWS")
    if runtime_truth.get("live_order_submit_allowed") is True:
        blockers.append("LIVE_ORDER_SUBMIT_UNEXPECTEDLY_ALLOWED")

    go_no_go = GO_READY if not blockers else GO_BLOCKED
    artifacts: dict[str, Any] = {
        "confidence_gate_block_distribution.json": distribution,
        "confidence_bucket_outcome_analysis.json": outcome_analysis,
        "paper_actionability_candidate_recovery.json": recovery,
        "loss_adjusted_paper_actionability_status.json": loss_adjusted,
        "calibrated_confidence_threshold_proposal.json": proposal,
        "paper_only_threshold_simulation.json": simulation,
        "post_calibration_paper_monitor_status.json": monitor,
    }
    artifacts["operator_dashboard_payload.json"] = build_operator_dashboard_payload(
        artifacts,
        runtime_truth,
        portfolio,
        generated_est=generated_est,
        go_no_go=go_no_go,
    )
    artifacts["operator_dashboard_payload.json"]["natural_language_context"] = {
        "explanation_rows": explanation_summary.get("explanation_rows"),
        "plain_english_payload_current": bool(explanation_payload),
        "message": (
            "Confidence is compressed near the paper gate. The proposed recovery is a "
            "paper-only simulation/trial using clean market-state rows, positive after-cost "
            "expected move, and no live threshold change."
        ),
    }
    if blockers:
        artifacts["operator_dashboard_payload.json"]["blockers"] = blockers

    return ConfidenceActionabilityResult(
        go_no_go=go_no_go,
        artifacts=artifacts,
        operator_dashboard_payload=artifacts["operator_dashboard_payload.json"],
    )


def _report(result: ConfidenceActionabilityResult, *, generated_est: str) -> str:
    dashboard = result.operator_dashboard_payload
    summary = _as_dict(dashboard.get("summary"))
    paper = _as_dict(dashboard.get("paper"))
    live = _as_dict(dashboard.get("live"))
    recovery = _as_dict(result.artifacts.get("paper_actionability_candidate_recovery.json"))
    proposal = _as_dict(result.artifacts.get("calibrated_confidence_threshold_proposal.json"))
    threshold = _as_dict(proposal.get("recommended_paper_only_trial")).get(
        "paper_confidence_threshold"
    )
    blockers = _as_list(dashboard.get("blockers"))
    blocker_text = "\n".join(f"- `{item}`" for item in blockers) if blockers else "- none"
    return f"""# V2 Confidence Calibration And Paper Actionability Improvement Report

Gate: `{result.go_no_go}`
Generated EST: `{generated_est}`
Prediction rows: `{summary.get("prediction_rows")}`
Paper-allowed prediction rows: `{summary.get("paper_fill_allowed_prediction_rows")}`
Confidence-blocked rows: `{summary.get("confidence_blocked_rows")}`
Under-confident paper-only candidates: `{recovery.get("under_confident_candidate_count")}`
Actionable after loss adjustment: `{recovery.get("actionable_after_loss_adjustment_candidate_count")}`
Loss-quarantine filtered candidates: `{recovery.get("loss_quarantine_filtered_under_confident_candidate_count")}`
Recommended paper-only trial threshold: `{threshold}`
Current allowed clean positive-edge overlap: `{summary.get("current_allowed_clean_positive_edge_overlap")}`
Paper threshold auto-applied: `False`
Live threshold changed: `False`
Live gate: `{live.get("live_gate")}`
Trader state: `{live.get("trader_state")}`
Live submit blocker: `{live.get("live_order_submit_blocker")}`
Paper equity: `{paper.get("equity")}`
Paper PnL: `{paper.get("pnl")}`

## Result

The confidence/actionability lane is complete as a read-only analysis and
paper-only simulation. The current model confidence head remains compressed near
the paper gate; no live risk, live threshold, leverage, margin, or exchange
execution behavior was changed.

## Blockers

{blocker_text}

## Recommendation

Use the proposed threshold only as an operator-approved paper-only trial with
clean market-state, positive after-cost expected move, and one-hour monitoring.
Keep live in balance hold until available margin satisfies the minimum order.

Safety: no real order/test-order/cancel/modify, no leverage or margin mutation,
no old Redis write, no legacy restart, no Redis trim, no raw credential output,
and no live threshold change.
"""


def write_confidence_actionability_artifacts(
    *,
    paths: ConfidenceActionabilityPaths,
    result: ConfidenceActionabilityResult,
    generated_est: str,
) -> ConfidenceActionabilityResult:
    all_artifacts = dict(result.artifacts)
    all_artifacts["GO_NO_GO.md"] = result.go_no_go
    all_artifacts[
        "V2_CONFIDENCE_CALIBRATION_AND_PAPER_ACTIONABILITY_IMPROVEMENT_REPORT.md"
    ] = _report(result, generated_est=generated_est)
    written: list[str] = []
    for directory in (paths.worklog_dir, paths.public_dir):
        directory.mkdir(parents=True, exist_ok=True)
        for filename, payload in all_artifacts.items():
            path = directory / filename
            if isinstance(payload, str):
                _write_text_atomic(path, payload)
            else:
                _write_text_atomic(path, dumps_pretty(payload))
            written.append(str(path))
    return ConfidenceActionabilityResult(
        go_no_go=result.go_no_go,
        artifacts=result.artifacts,
        operator_dashboard_payload=result.operator_dashboard_payload,
        paths_written=tuple(written),
    )


def run_confidence_actionability(
    *,
    repo_root: Path,
    generated_est: str | None = None,
) -> ConfidenceActionabilityResult:
    generated_est = generated_est or _est_iso()
    paths = default_paths(repo_root)
    result = build_confidence_actionability(
        prediction_source=_read_json(paths.prediction_source_path),
        runtime_truth=_read_json(paths.runtime_truth_path),
        portfolio=_read_json(paths.portfolio_path),
        outcome_observer=_read_json(paths.outcome_observer_path),
        explanation_payload=_read_json(paths.explanation_path),
        generated_est=generated_est,
        paper_feedback_payload=_read_json(paths.paper_feedback_path),
        bucket_quarantine_status=_read_json(paths.bucket_quarantine_path),
    )
    return write_confidence_actionability_artifacts(
        paths=paths,
        result=result,
        generated_est=generated_est,
    )
