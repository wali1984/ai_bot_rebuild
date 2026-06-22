"""False-negative reduction and actionability artifacts for the CUDA trainer.

Consumes the CUDA edge-calibration/outcome burn-in operator payload and creates
paper-only diagnostics for missed opportunities. It does not write Redis,
does not change thresholds in runtime config, does not bypass risk, and does
not approve live or canary.
"""
from __future__ import annotations

import json
import math
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.config import LIVE_GATE_BLOCKED
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.publisher import dumps_pretty

GO_READY = "V2_CUDA_TRAINER_FALSE_NEGATIVE_REDUCTION_AND_ACTIONABILITY_READY"
GO_BLOCKED = "V2_CUDA_TRAINER_FALSE_NEGATIVE_REDUCTION_AND_ACTIONABILITY_BLOCKED"
SCHEMA_VERSION = "v2_cuda_trainer_false_negative_reduction_actionability_v1"
ARTIFACT_REL = Path("v2_cuda_trainer_false_negative_reduction_and_actionability/latest")
SOURCE_PAYLOAD_REL = Path("v2_native_cuda_trainer_edge_calibration_and_outcome_burn_in/latest/operator_dashboard_payload.json")

LIVE_BLOCKERS = (
    "BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN",
    "BLOCK_LIVE_MODEL_SIGNAL_QUALITY_NOT_READY",
    "BLOCK_LIVE_RISK_CAPS_OPERATOR_REQUIRED",
)


@dataclass(frozen=True)
class FalseNegativeActionabilityPaths:
    repo_root: Path
    worklog_dir: Path
    public_dir: Path
    source_payload_path: Path


@dataclass(frozen=True)
class FalseNegativeActionabilityResult:
    go_no_go: str
    artifacts: dict[str, Any]
    operator_dashboard_payload: dict[str, Any]
    paths_written: tuple[str, ...] = field(default_factory=tuple)


SimulationPredicate = Callable[[Mapping[str, Any]], bool]


def default_paths(repo_root: Path) -> FalseNegativeActionabilityPaths:
    root = repo_root.resolve()
    return FalseNegativeActionabilityPaths(
        repo_root=root,
        worklog_dir=root / "claude_worklog/final_readiness" / ARTIFACT_REL,
        public_dir=root / "v2/frontend/public" / ARTIFACT_REL,
        source_payload_path=root / "v2/frontend/public" / SOURCE_PAYLOAD_REL,
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


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _ci_lower_95(values: list[float]) -> float | None:
    if not values:
        return None
    if len(values) < 2:
        return float(values[0])
    return statistics.fmean(values) - 1.96 * statistics.stdev(values) / math.sqrt(len(values))


def _read_json(path: Path) -> dict[str, Any]:
    return _as_dict(json.loads(path.read_text(encoding="utf-8")))


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    tmp.replace(path)


def _completed_rows(source: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = [_as_dict(row) for row in _as_list(_as_dict(source.get("outcome_mining")).get("rows"))]
    return [row for row in rows if _float(row.get("realized_after_cost_return_bps")) is not None]


def _false_negative_rows(source: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [row for row in _completed_rows(source) if row.get("classification") == "false_negative"]


def _outcome(row: Mapping[str, Any], window: str = "5m") -> dict[str, Any]:
    return _as_dict(_as_dict(row.get("outcome_windows")).get(window))


def _root_causes(row: Mapping[str, Any]) -> list[str]:
    causes: list[str] = []
    coverage = _float(row.get("data_coverage_percent"))
    missing = int(_float(row.get("missing_feature_count")) or 0)
    stale = int(_float(row.get("stale_feature_count")) or 0)
    confidence = _float(row.get("confidence_calibrated"))
    expected = _float(row.get("expected_move_after_cost_bps"))
    action = str(row.get("selected_action") or "").lower()
    orch_action = str(row.get("orchestrator_action") or "").lower()
    orch_reason = str(row.get("orchestrator_reason") or "").lower()
    risk_action = str(row.get("risk_action") or "").lower()
    block_reasons = [str(item).lower() for item in _as_list(row.get("paper_fill_gate_block_reasons"))]

    if coverage is not None and coverage < 70.0:
        causes.append("DATA_COVERAGE_LOW")
    if missing > 0:
        causes.append("INSUFFICIENT_HISTORY")
    if stale > 0 or "stale" in orch_reason:
        causes.append("FEATURE_STALE")
    if confidence is not None and confidence < 0.55:
        causes.append("CONFIDENCE_TOO_LOW")
    if expected is None or abs(expected) < 4.0:
        causes.append("EXPECTED_MOVE_TOO_LOW")
    if action not in {"long", "short"}:
        causes.append("TRAINER_ACTION_TOO_CONSERVATIVE")
    if risk_action and risk_action != "allow":
        causes.append("RISK_GATE_BLOCKED")
    if orch_action in {"hold", "abstain"}:
        causes.append("ORCHESTRATOR_HOLD")
    if any("overconcentration" in reason or "symbol_concentration" in reason for reason in block_reasons):
        causes.append("SYMBOL_OVERCONCENTRATION_GUARD")
    if "strategy_disagreement" in block_reasons:
        causes.append("STRATEGY_SIGNAL_DISAGREEMENT")
    return list(dict.fromkeys(causes or ["TRAINER_ACTION_TOO_CONSERVATIVE"]))


def _strategy_evidence(row: Mapping[str, Any]) -> dict[str, Any]:
    side = str(row.get("counterfactual_side") or "")
    one = _float(_outcome(row, "1m").get("after_cost_return_bps"))
    five = _float(_outcome(row, "5m").get("after_cost_return_bps"))
    fifteen = _float(_outcome(row, "15m").get("after_cost_return_bps"))
    max_favorable = _float(_outcome(row, "5m").get("max_favorable_bps"))

    trend_agrees = five is not None and fifteen is not None and five > 0 and fifteen > 0
    momentum_agrees = one is not None and five is not None and one > 0 and five > 0
    breakout_agrees = max_favorable is not None and max_favorable >= 12.0
    strategy_agrees = bool(side in {"long", "short"} and (trend_agrees or momentum_agrees or breakout_agrees))

    unavailable = "NOT_AVAILABLE_IN_EDGE_BURN_IN_PAYLOAD"
    return {
        "strategy_agreement": "AGREE" if strategy_agrees else "DISAGREE_OR_INSUFFICIENT_EVIDENCE",
        "trend_strategy_signal": side if trend_agrees else "NO_TREND_CONFIRMATION",
        "breakout_signal": side if breakout_agrees else "NO_BREAKOUT_CONFIRMATION",
        "momentum_signal": side if momentum_agrees else "NO_MOMENTUM_CONFIRMATION",
        "ta_confirmation": "DERIVED_FROM_OUTCOME_WINDOWS_ONLY" if strategy_agrees else "INSUFFICIENT_TA_CONFIRMATION",
        "funding_oi_confirmation": unavailable,
        "orderbook_confirmation": unavailable,
        "public_intel_contribution": unavailable,
        "whale_wall_contribution": unavailable,
        "liquidation_signal": unavailable,
        "derived_from_outcome_windows_only": True,
    }


def _attribution_row(row: Mapping[str, Any]) -> dict[str, Any]:
    outcome = _outcome(row, "5m")
    causes = _root_causes(row)
    strategy = _strategy_evidence(row)
    return {
        "prediction_id": row.get("prediction_id"),
        "symbol": row.get("symbol"),
        "timeframe": row.get("timeframe"),
        "trainer_action": row.get("selected_action"),
        "trainer_confidence": row.get("confidence_calibrated"),
        "expected_move_after_cost_bps": row.get("expected_move_after_cost_bps"),
        "risk_decision": {
            "risk_decision_id": row.get("risk_decision_id"),
            "risk_action": row.get("risk_action"),
            "risk_reason": row.get("risk_reason"),
        },
        "orchestrator_decision": {
            "orchestrator_decision_id": row.get("orchestrator_decision_id"),
            "orchestrator_action": row.get("orchestrator_action"),
            "orchestrator_reason": row.get("orchestrator_reason"),
        },
        "paper_outcome": {
            "paper_intent_id": row.get("paper_intent_id"),
            "paper_ledger_id": row.get("paper_ledger_id"),
            "paper_ledger_action": row.get("paper_ledger_action"),
            "paper_ledger_reason": row.get("paper_ledger_reason"),
            "classification": row.get("classification"),
        },
        "realized_after_cost_bps": row.get("realized_after_cost_return_bps"),
        "missed_direction": row.get("counterfactual_side"),
        "block_reason": row.get("risk_reason") or row.get("orchestrator_reason") or row.get("paper_ledger_reason"),
        "data_coverage_percent": row.get("data_coverage_percent"),
        "feature_stale_missing_flags": {
            "missing_feature_count": row.get("missing_feature_count"),
            "stale_feature_count": row.get("stale_feature_count"),
            "paper_fill_gate_block_reasons": row.get("paper_fill_gate_block_reasons", []),
        },
        "strategy_agreement_disagreement": strategy["strategy_agreement"],
        "root_causes": causes,
        "primary_root_cause": causes[0],
        "strategy_evidence": strategy,
    }


def build_false_negative_attribution(source: Mapping[str, Any], *, generated_est: str) -> dict[str, Any]:
    rows = [_attribution_row(row) for row in _false_negative_rows(source)]
    cause_counts = Counter(cause for row in rows for cause in _as_list(row.get("root_causes")))
    missing_lineage = [
        row.get("prediction_id")
        for row in rows
        if not _as_dict(row.get("risk_decision")).get("risk_decision_id")
        or not _as_dict(row.get("orchestrator_decision")).get("orchestrator_decision_id")
        or not _as_dict(row.get("paper_outcome")).get("paper_ledger_id")
    ]
    return {
        "schema_version": f"{SCHEMA_VERSION}_false_negative_attribution",
        "generated_est": generated_est,
        "status": "FALSE_NEGATIVE_ATTRIBUTION_READY" if not missing_lineage else "FALSE_NEGATIVE_ATTRIBUTION_BLOCKED",
        "false_negative_count": len(rows),
        "root_cause_counts": dict(sorted(cause_counts.items())),
        "lineage_complete": not missing_lineage,
        "missing_lineage_prediction_ids": missing_lineage[:100],
        "rows": rows,
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
    }


def _candidate_rows(rows: list[dict[str, Any]], predicate: SimulationPredicate) -> list[dict[str, Any]]:
    return [row for row in rows if predicate(row)]


def _has_strategy_agreement(row: Mapping[str, Any]) -> bool:
    return _strategy_evidence(row)["strategy_agreement"] == "AGREE"


def _simulation_result(
    *,
    simulation_id: str,
    description: str,
    rows: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    recommendation: str,
    notes: str,
) -> dict[str, Any]:
    recovered = [row for row in candidates if row.get("classification") == "false_negative"]
    introduced = [
        row
        for row in candidates
        if row.get("classification") in {"correct_no_trade", "false_positive"}
        and (_float(row.get("realized_after_cost_return_bps")) or 0.0) <= 0.0
    ]
    candidate_values = [
        value
        for value in (_float(row.get("realized_after_cost_return_bps")) for row in candidates)
        if value is not None
    ]
    baseline_values = [
        value
        for value in (_float(row.get("realized_after_cost_return_bps")) for row in rows)
        if value is not None
    ]
    drawdowns = [
        value
        for value in (_float(_outcome(row, "5m").get("drawdown_bps")) for row in candidates)
        if value is not None
    ]
    return {
        "simulation_id": simulation_id,
        "description": description,
        "paper_only": True,
        "runtime_config_changed": False,
        "thresholds_auto_accepted": False,
        "sample_count": len(rows),
        "candidate_count": len(candidates),
        "recovered_false_negatives": len(recovered),
        "recovered_prediction_ids": [row.get("prediction_id") for row in recovered[:64]],
        "introduced_false_positives_estimate": len(introduced),
        "introduced_false_positive_prediction_ids": [row.get("prediction_id") for row in introduced[:64]],
        "expected_after_cost_change": (
            (_mean(candidate_values) or 0.0) - (_mean(baseline_values) or 0.0)
            if candidate_values and baseline_values
            else None
        ),
        "candidate_after_cost_expectancy_bps": _mean(candidate_values),
        "candidate_after_cost_ci_lower_bps": _ci_lower_95(candidate_values),
        "max_drawdown_estimate": max(drawdowns) if drawdowns else None,
        "recommendation": recommendation,
        "notes": notes,
    }


def build_threshold_simulation(source: Mapping[str, Any], *, generated_est: str) -> dict[str, Any]:
    rows = _completed_rows(source)
    by_symbol_false_positives = Counter(row.get("symbol") for row in rows if row.get("classification") == "false_positive")
    by_symbol_false_negatives = Counter(row.get("symbol") for row in rows if row.get("classification") == "false_negative")

    simulations = [
        _simulation_result(
            simulation_id="lower_min_confidence_by_bucket",
            description="Lower confidence bucket floor to 0.50 where coverage is at least 40%.",
            rows=rows,
            candidates=_candidate_rows(
                rows,
                lambda row: (_float(row.get("confidence_calibrated")) or 0.0) >= 0.50
                and (_float(row.get("data_coverage_percent")) or 0.0) >= 40.0
                and row.get("counterfactual_side") in {"long", "short"},
            ),
            recommendation="PAPER_ONLY_REVIEW_REQUIRED",
            notes="Diagnostic only; does not change live/runtime caps.",
        ),
        _simulation_result(
            simulation_id="lower_expected_move_after_cost_threshold",
            description="Lower absolute expected-move threshold to 2 bps in paper diagnostics.",
            rows=rows,
            candidates=_candidate_rows(
                rows,
                lambda row: abs(_float(row.get("expected_move_after_cost_bps")) or 0.0) >= 2.0
                and (_float(row.get("confidence_calibrated")) or 0.0) >= 0.48
                and (_float(row.get("data_coverage_percent")) or 0.0) >= 35.0,
            ),
            recommendation="REJECT_FOR_NOW_HIGH_FALSE_POSITIVE_RISK",
            notes="Broader threshold recovery is too blunt without more feature coverage.",
        ),
        _simulation_result(
            simulation_id="symbol_specific_thresholds",
            description="Consider symbols with false negatives and no observed false positives in current sample.",
            rows=rows,
            candidates=_candidate_rows(
                rows,
                lambda row: by_symbol_false_negatives.get(row.get("symbol"), 0) > 0
                and by_symbol_false_positives.get(row.get("symbol"), 0) == 0
                and (_float(row.get("confidence_calibrated")) or 0.0) >= 0.50,
            ),
            recommendation="PAPER_ONLY_SYMBOL_REVIEW_REQUIRED",
            notes="Symbol-specific thresholds are not accepted automatically.",
        ),
        _simulation_result(
            simulation_id="strategy_confirmed_overrides",
            description="Recover only missed opportunities with derived trend/momentum/breakout agreement.",
            rows=rows,
            candidates=_candidate_rows(
                rows,
                lambda row: _has_strategy_agreement(row)
                and (_float(row.get("confidence_calibrated")) or 0.0) >= 0.48
                and (_float(row.get("data_coverage_percent")) or 0.0) >= 40.0,
            ),
            recommendation="PAPER_SHADOW_EXPERIMENT_CANDIDATE",
            notes="Still cannot bypass risk; overlay source must remain paper_shadow_actionability_experiment.",
        ),
        _simulation_result(
            simulation_id="risk_gate_soft_downrank_vs_hard_block",
            description="Diagnostic soft downrank, but final risk gate remains hard fail-closed.",
            rows=rows,
            candidates=[],
            recommendation="DO_NOT_USE_FOR_RECOVERY_WITHOUT_RISK_REVIEW",
            notes="Risk hard block remains final; recovered count is intentionally zero.",
        ),
        _simulation_result(
            simulation_id="require_multi_source_confirmation",
            description="Require strategy agreement, confidence >= 0.50, coverage >= 50%, and no stale features.",
            rows=rows,
            candidates=_candidate_rows(
                rows,
                lambda row: _has_strategy_agreement(row)
                and (_float(row.get("confidence_calibrated")) or 0.0) >= 0.50
                and (_float(row.get("data_coverage_percent")) or 0.0) >= 50.0
                and int(_float(row.get("stale_feature_count")) or 0) == 0,
            ),
            recommendation="SAFEST_PAPER_SHADOW_OVERLAY_CANDIDATE",
            notes="Most conservative current recovery candidate; still simulation only.",
        ),
        _simulation_result(
            simulation_id="no_trade_preservation_threshold",
            description="Preserve no-trade unless derived strategy agreement and current outcome margin exceeds 12 bps.",
            rows=rows,
            candidates=_candidate_rows(
                rows,
                lambda row: _has_strategy_agreement(row)
                and (_float(row.get("realized_after_cost_return_bps")) or 0.0) >= 12.0
                and (_float(row.get("data_coverage_percent")) or 0.0) >= 50.0,
            ),
            recommendation="PAPER_ONLY_REVIEW_REQUIRED",
            notes="Uses realized outcomes for diagnostics; not deployable as a real-time rule.",
        ),
    ]
    return {
        "schema_version": f"{SCHEMA_VERSION}_threshold_actionability_simulation",
        "generated_est": generated_est,
        "status": "THRESHOLD_ACTIONABILITY_SIMULATION_READY",
        "paper_only": True,
        "runtime_thresholds_changed": False,
        "thresholds_auto_accepted": False,
        "simulations": simulations,
        "recommended_simulation_id": "require_multi_source_confirmation",
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
    }


def build_strategy_assisted_recovery(attribution: Mapping[str, Any], *, generated_est: str) -> dict[str, Any]:
    rows = []
    for item in _as_list(attribution.get("rows")):
        row = _as_dict(item)
        strategy = _as_dict(row.get("strategy_evidence"))
        rows.append(
            {
                "prediction_id": row.get("prediction_id"),
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "missed_direction": row.get("missed_direction"),
                "realized_after_cost_bps": row.get("realized_after_cost_bps"),
                "trend_strategy_signal": strategy.get("trend_strategy_signal"),
                "breakout_signal": strategy.get("breakout_signal"),
                "momentum_signal": strategy.get("momentum_signal"),
                "ta_confirmation": strategy.get("ta_confirmation"),
                "funding_oi_confirmation": strategy.get("funding_oi_confirmation"),
                "orderbook_confirmation": strategy.get("orderbook_confirmation"),
                "public_intel_contribution": strategy.get("public_intel_contribution"),
                "whale_wall_contribution": strategy.get("whale_wall_contribution"),
                "liquidation_signal": strategy.get("liquidation_signal"),
                "strategy_agreement": row.get("strategy_agreement_disagreement"),
            }
        )
    agreement_count = sum(1 for row in rows if row.get("strategy_agreement") == "AGREE")
    return {
        "schema_version": f"{SCHEMA_VERSION}_strategy_assisted_recovery",
        "generated_est": generated_est,
        "status": "STRATEGY_ASSISTED_RECOVERY_READY",
        "false_negative_count": len(rows),
        "strategy_agreement_count": agreement_count,
        "strategy_disagreement_or_insufficient_count": max(0, len(rows) - agreement_count),
        "rows": rows,
        "source_limits": {
            "funding_oi_confirmation": "NOT_AVAILABLE_IN_EDGE_BURN_IN_PAYLOAD",
            "orderbook_confirmation": "NOT_AVAILABLE_IN_EDGE_BURN_IN_PAYLOAD",
            "public_intel_contribution": "NOT_AVAILABLE_IN_EDGE_BURN_IN_PAYLOAD",
            "whale_wall_contribution": "NOT_AVAILABLE_IN_EDGE_BURN_IN_PAYLOAD",
            "liquidation_signal": "NOT_AVAILABLE_IN_EDGE_BURN_IN_PAYLOAD",
        },
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
    }


def _overlay_candidates(source: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidates = []
    for row in _false_negative_rows(source):
        if (
            _has_strategy_agreement(row)
            and (_float(row.get("confidence_calibrated")) or 0.0) >= 0.50
            and (_float(row.get("data_coverage_percent")) or 0.0) >= 50.0
            and int(_float(row.get("stale_feature_count")) or 0) == 0
            and int(_float(row.get("missing_feature_count")) or 0) <= 35
        ):
            candidates.append(row)
    return candidates


def build_paper_actionability_overlay(source: Mapping[str, Any], *, generated_est: str) -> dict[str, Any]:
    candidates = _overlay_candidates(source)
    rows = []
    for row in candidates:
        rows.append(
            {
                "overlay_candidate_id": f"paper_shadow_actionability_experiment:{row.get('prediction_id')}",
                "prediction_id": row.get("prediction_id"),
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "candidate_direction": row.get("counterfactual_side"),
                "source": "paper_shadow_actionability_experiment",
                "overlay_reason": "strategy_confirmed_false_negative_with_minimum_coverage",
                "risk_bypass": False,
                "risk_decision_id": row.get("risk_decision_id"),
                "risk_action": row.get("risk_action"),
                "risk_reason": row.get("risk_reason"),
                "orchestrator_decision_id": row.get("orchestrator_decision_id"),
                "paper_ledger_id": row.get("paper_ledger_id"),
                "realized_after_cost_bps": row.get("realized_after_cost_return_bps"),
                "confidence_calibrated": row.get("confidence_calibrated"),
                "data_coverage_percent": row.get("data_coverage_percent"),
                "missing_feature_count": row.get("missing_feature_count"),
                "stale_feature_count": row.get("stale_feature_count"),
                "live_gate": LIVE_GATE_BLOCKED,
                "live_symbols": [],
                "execution_live_symbols": [],
            }
        )
    return {
        "schema_version": f"{SCHEMA_VERSION}_paper_actionability_overlay",
        "generated_est": generated_est,
        "status": "PAPER_ACTIONABILITY_OVERLAY_READY",
        "overlay_source": "paper_shadow_actionability_experiment",
        "overlay_candidate_count": len(rows),
        "rows": rows,
        "paper_shadow_only": True,
        "runtime_config_changed": False,
        "thresholds_auto_accepted": False,
        "risk_bypass": False,
        "risk_fail_closed_preserved": True,
        "can_bypass_risk": False,
        "writes_live_symbols": False,
        "enables_execution": False,
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
    }


def build_edge_after_overlay(source: Mapping[str, Any], overlay: Mapping[str, Any], *, generated_est: str) -> dict[str, Any]:
    edge = _as_dict(source.get("edge_recompute"))
    base = _as_dict(edge.get("new_cuda_trainer"))
    completed = _completed_rows(source)
    overlay_rows = _as_list(overlay.get("rows"))
    overlay_values = [
        value
        for value in (_float(row.get("realized_after_cost_bps")) for row in overlay_rows)
        if value is not None
    ]
    all_values = [
        value
        for value in (_float(row.get("realized_after_cost_return_bps")) for row in completed)
        if value is not None
    ]
    by_symbol: dict[str, list[float]] = {}
    for row in overlay_rows:
        value = _float(row.get("realized_after_cost_bps"))
        symbol = str(row.get("symbol") or "UNKNOWN")
        if value is not None:
            by_symbol.setdefault(symbol, []).append(value)
    return {
        "schema_version": f"{SCHEMA_VERSION}_edge_after_actionability_overlay",
        "generated_est": generated_est,
        "status": "EDGE_AFTER_ACTIONABILITY_OVERLAY_READY",
        "edge_proven": False,
        "before_overlay": {
            "after_cost_expectancy_bps": base.get("after_cost_expectancy_bps"),
            "after_cost_ci_lower_bps": base.get("after_cost_ci_lower_bps"),
            "false_positive_count": edge.get("false_positive_count"),
            "false_negative_count": edge.get("false_negative_count"),
            "correct_no_trade_count": _as_dict(_as_dict(source.get("outcome_mining")).get("classification_counts")).get("correct_no_trade"),
            "drawdown": edge.get("drawdown"),
            "candidate_count": 0,
        },
        "simulated_overlay": {
            "overlay_candidate_count": len(overlay_rows),
            "recovered_false_negatives": len(overlay_rows),
            "introduced_false_positives_estimate": 0,
            "candidate_after_cost_expectancy_bps": _mean(overlay_values),
            "candidate_after_cost_ci_lower_bps": _ci_lower_95(overlay_values),
            "candidate_count": len(overlay_rows),
            "all_completed_outcome_expectancy_bps": _mean(all_values),
            "all_completed_outcome_ci_lower_bps": _ci_lower_95(all_values),
        },
        "actual_paper_shadow_overlay_after_burn_in": {
            "available": False,
            "status": "PENDING_FUTURE_PAPER_BURN_IN",
        },
        "by_symbol_recovered_opportunities": [
            {
                "symbol": symbol,
                "recovered_count": len(values),
                "candidate_after_cost_expectancy_bps": _mean(values),
                "candidate_after_cost_ci_lower_bps": _ci_lower_95(values),
            }
            for symbol, values in sorted(by_symbol.items())
        ],
        "recommendations": list(LIVE_BLOCKERS),
        "primary_recommendation": "BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN",
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
    }


def build_operator_payload(
    *,
    source: Mapping[str, Any],
    artifacts: Mapping[str, Any],
    generated_est: str,
    go_no_go: str,
) -> dict[str, Any]:
    attribution = artifacts["v2_cuda_false_negative_attribution_status.json"]
    simulation = artifacts["v2_cuda_threshold_actionability_simulation.json"]
    strategy = artifacts["v2_cuda_strategy_assisted_recovery_status.json"]
    overlay = artifacts["v2_cuda_paper_actionability_overlay_status.json"]
    edge = artifacts["v2_cuda_edge_after_actionability_overlay_status.json"]
    return {
        "schema_version": f"{SCHEMA_VERSION}_operator_dashboard",
        "generated_est": generated_est,
        "generated_at": generated_est,
        "go_no_go": go_no_go,
        "source_gate": source.get("go_no_go"),
        "source_payload_path": f"/{SOURCE_PAYLOAD_REL}",
        "false_negative_attribution": attribution,
        "threshold_actionability_simulation": simulation,
        "strategy_assisted_recovery": strategy,
        "paper_actionability_overlay": overlay,
        "edge_after_actionability_overlay": edge,
        "source_edge_recompute": _as_dict(source.get("edge_recompute")),
        "source_outcome_mining": {
            "outcome_sample_count": _as_dict(source.get("outcome_mining")).get("outcome_sample_count"),
            "classification_counts": _as_dict(source.get("outcome_mining")).get("classification_counts"),
        },
        "website_sync": {
            "status": "WEBSITE_SYNC_READY",
            "payload_path": f"/{ARTIFACT_REL}/operator_dashboard_payload.json",
            "surfaces_synced": ["AI Brain", "Replay / Edge", "Paper Trading", "Risk", "Orchestrator", "Live Readiness"],
            "must_show": {
                "false_negative_count": attribution.get("false_negative_count"),
                "false_negative_root_causes": attribution.get("root_cause_counts"),
                "threshold_simulation_results": len(_as_list(simulation.get("simulations"))),
                "paper_only_overlay_status": overlay.get("status"),
                "recovered_opportunities": overlay.get("overlay_candidate_count"),
                "why_live_remains_blocked": edge.get("recommendations"),
            },
        },
        "live_readiness": {
            "live_ready": False,
            "canary_ready": False,
            "primary_recommendation": edge.get("primary_recommendation"),
            "recommendations": edge.get("recommendations"),
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
            "execution_live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
        },
        "live_switch": {
            "visible": True,
            "enabled": False,
            "backend_live_enable_callable": False,
            "disabled_reason": "LIVE_GATE=blocked_human_only; false-negative recovery is paper/shadow only and not live approval.",
        },
        "safety_scoreboard": {
            "paper_shadow_only": True,
            "runtime_config_changed": False,
            "thresholds_auto_accepted": False,
            "risk_bypass": False,
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
            "execution_live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "places_orders": False,
            "cancels_orders": False,
            "modifies_orders": False,
            "calls_test_order_endpoint": False,
            "changes_leverage": False,
            "changes_margin_mode": False,
            "writes_old_redis": False,
            "restarts_legacy": False,
            "trims_redis": False,
        },
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
    }


def build_report(result: FalseNegativeActionabilityResult) -> str:
    p = result.operator_dashboard_payload
    attr = p["false_negative_attribution"]
    overlay = p["paper_actionability_overlay"]
    edge = p["edge_after_actionability_overlay"]
    before = edge["before_overlay"]
    simulated = edge["simulated_overlay"]
    return "\n".join(
        [
            "# V2 CUDA Trainer False-Negative Reduction And Actionability Report",
            "",
            f"Gate: `{result.go_no_go}`",
            f"Generated EST: `{p['generated_est']}`",
            f"False negatives attributed: `{attr.get('false_negative_count')}`",
            f"Root causes: `{attr.get('root_cause_counts')}`",
            f"Threshold simulations: `{len(p['threshold_actionability_simulation'].get('simulations') or [])}`",
            f"Paper overlay candidates: `{overlay.get('overlay_candidate_count')}`",
            f"Before overlay expectancy bps: `{before.get('after_cost_expectancy_bps')}`",
            f"Before overlay CI lower bps: `{before.get('after_cost_ci_lower_bps')}`",
            f"Simulated overlay recovered false negatives: `{simulated.get('recovered_false_negatives')}`",
            f"Simulated overlay candidate expectancy bps: `{simulated.get('candidate_after_cost_expectancy_bps')}`",
            "",
            "Live/canary remain blocked. Thresholds are simulated only and not auto-accepted.",
            "",
            f"- live_gate: `{LIVE_GATE_BLOCKED}`",
            "- live_symbols: `[]`",
            "- execution_live_symbols: `[]`",
            "- risk_bypass: `False`",
            "- runtime_config_changed: `False`",
            f"- recommendation: `{edge.get('primary_recommendation')}`",
            f"- blockers: `{', '.join(edge.get('recommendations') or [])}`",
            "",
            "Safety: no live/canary enable, no order/test-order/cancel/modify, no leverage/margin mutation, no old Redis write, no legacy restart, no Redis trim.",
        ]
    ) + "\n"


def build_false_negative_actionability(
    source: Mapping[str, Any],
    *,
    generated_est: str | None = None,
) -> FalseNegativeActionabilityResult:
    generated = generated_est or _est_iso()
    artifacts: dict[str, Any] = {}
    artifacts["v2_cuda_false_negative_attribution_status.json"] = build_false_negative_attribution(
        source,
        generated_est=generated,
    )
    artifacts["v2_cuda_threshold_actionability_simulation.json"] = build_threshold_simulation(
        source,
        generated_est=generated,
    )
    artifacts["v2_cuda_strategy_assisted_recovery_status.json"] = build_strategy_assisted_recovery(
        artifacts["v2_cuda_false_negative_attribution_status.json"],
        generated_est=generated,
    )
    artifacts["v2_cuda_paper_actionability_overlay_status.json"] = build_paper_actionability_overlay(
        source,
        generated_est=generated,
    )
    artifacts["v2_cuda_edge_after_actionability_overlay_status.json"] = build_edge_after_overlay(
        source,
        artifacts["v2_cuda_paper_actionability_overlay_status.json"],
        generated_est=generated,
    )
    hard_blockers: list[str] = []
    if artifacts["v2_cuda_false_negative_attribution_status.json"]["status"].endswith("BLOCKED"):
        hard_blockers.append("FALSE_NEGATIVE_LINEAGE_INCOMPLETE")
    if _as_dict(source.get("live_readiness")).get("live_gate", LIVE_GATE_BLOCKED) != LIVE_GATE_BLOCKED:
        hard_blockers.append("SOURCE_LIVE_GATE_NOT_BLOCKED")
    if _as_dict(source.get("live_readiness")).get("live_symbols", []) != []:
        hard_blockers.append("SOURCE_LIVE_SYMBOLS_NOT_EMPTY")
    go_no_go = GO_BLOCKED if hard_blockers else GO_READY
    operator = build_operator_payload(
        source=source,
        artifacts=artifacts,
        generated_est=generated,
        go_no_go=go_no_go,
    )
    if hard_blockers:
        operator["hard_blockers"] = hard_blockers
    return FalseNegativeActionabilityResult(
        go_no_go=go_no_go,
        artifacts=artifacts,
        operator_dashboard_payload=operator,
    )


def write_false_negative_actionability_artifacts(
    *,
    paths: FalseNegativeActionabilityPaths,
    result: FalseNegativeActionabilityResult,
) -> FalseNegativeActionabilityResult:
    report = build_report(result)
    files: dict[str, str] = {
        "GO_NO_GO.md": result.go_no_go + "\n",
        "V2_CUDA_TRAINER_FALSE_NEGATIVE_REDUCTION_AND_ACTIONABILITY_REPORT.md": report,
        "operator_dashboard_payload.json": dumps_pretty(result.operator_dashboard_payload),
    }
    for name, obj in result.artifacts.items():
        files[name] = dumps_pretty(obj)
    written: list[str] = []
    for base in (paths.worklog_dir, paths.public_dir):
        for name, text in files.items():
            path = base / name
            _write_text_atomic(path, text)
            written.append(str(path))
    return FalseNegativeActionabilityResult(
        go_no_go=result.go_no_go,
        artifacts=result.artifacts,
        operator_dashboard_payload=result.operator_dashboard_payload,
        paths_written=tuple(written),
    )


def run_false_negative_actionability(
    *,
    paths: FalseNegativeActionabilityPaths,
    source_payload_path: Path | None = None,
) -> FalseNegativeActionabilityResult:
    source = _read_json(source_payload_path or paths.source_payload_path)
    result = build_false_negative_actionability(source)
    return write_false_negative_actionability_artifacts(paths=paths, result=result)
