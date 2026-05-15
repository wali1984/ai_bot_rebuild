from __future__ import annotations

import hashlib
from typing import Any, Mapping

from v2.backend.app.services.legacy_v2_observatory_common import (
    LIVE_GATE_STATUS,
    as_float,
    as_list,
    confidence_bucket,
    nested_get,
    safety_footer,
    utc_now,
)


def _present(value: Any) -> bool:
    return value not in (None, "", [], {})


def _v2_allows(paper_status: Mapping[str, Any], risk_status: Mapping[str, Any]) -> bool:
    action = (
        nested_get(paper_status, "current_risk_decision.risk_action")
        or risk_status.get("risk_action")
        or risk_status.get("input_risk_action")
    )
    fill = (
        nested_get(paper_status, "last_paper_event.fill_recorded")
        or nested_get(paper_status, "last_paper_event.fill_allowed")
        or risk_status.get("ledger_action") == "record_allow"
    )
    return str(action).lower() in {"allow", "approved"} and bool(fill)


def _legacy_allows(legacy_status: Mapping[str, Any]) -> bool:
    if not _present(legacy_status.get("latest_prediction_id")):
        return False
    reason = str(legacy_status.get("latest_signal_reason") or "").lower()
    if "block" in reason or "deny" in reason:
        return False
    return True


def _cost_breakdown(paper_status: Mapping[str, Any], paper_exec_status: Mapping[str, Any]) -> dict[str, Any]:
    canary = nested_get(paper_status, "current_risk_decision.canary_profile_tightening", {})
    return {
        "fee_bps": nested_get(canary, "fee_bps"),
        "spread_bps": nested_get(canary, "spread_bps"),
        "slippage_bps": nested_get(canary, "slippage_bps")
        or paper_exec_status.get("paper_filter_estimated_cost_bps"),
        "funding_risk_bps": nested_get(canary, "funding_risk_bps"),
        "estimated_cost_bps": nested_get(canary, "estimated_cost_bps")
        or paper_exec_status.get("paper_filter_estimated_cost_bps"),
    }


def _comparison_result(legacy_allow: bool, v2_allow: bool, legacy_present: bool, v2_present: bool) -> str:
    if not legacy_present and v2_present:
        return "LEGACY_SIGNAL_MISSING_V2_PRESENT"
    if legacy_present and not v2_present:
        return "LEGACY_PRESENT_V2_MISSING"
    if not legacy_present and not v2_present:
        return "MISSING_EVIDENCE_CANNOT_COMPARE"
    if legacy_allow and v2_allow:
        return "BOTH_ALLOW"
    if legacy_allow and not v2_allow:
        return "LEGACY_ALLOW_V2_BLOCK"
    if not legacy_allow and v2_allow:
        return "LEGACY_BLOCK_V2_ALLOW"
    return "BOTH_BLOCK"


def _disagreement_reasons(
    *,
    paper_status: Mapping[str, Any],
    trainer_status: Mapping[str, Any],
    symbol_status: Mapping[str, Any],
    risk_status: Mapping[str, Any],
    paper_exec_status: Mapping[str, Any],
) -> list[str]:
    reasons: list[str] = []
    trainer_source = (
        nested_get(paper_status, "trainer_prediction.source_type")
        or trainer_status.get("prediction_source_type")
        or trainer_status.get("prediction_source")
    )
    feature_state = (
        nested_get(paper_status, "feature_snapshot.freshness_state")
        or nested_get(paper_status, "trainer_prediction.freshness_state")
    )
    canary = nested_get(paper_status, "current_risk_decision.canary_profile_tightening", {})
    expected_move = (
        nested_get(canary, "expected_move_bps")
        or paper_exec_status.get("paper_filter_expected_move_bps")
    )
    cost = nested_get(canary, "estimated_cost_bps") or paper_exec_status.get(
        "paper_filter_estimated_cost_bps"
    )
    symbol = nested_get(paper_status, "trainer_prediction.symbol") or paper_exec_status.get("symbol")
    if not _present(trainer_source):
        reasons.append("trainer_source_missing")
    if not _present(nested_get(paper_status, "feature_snapshot.feature_snapshot_id")):
        reasons.append("feature_snapshot_missing")
    if not _present(feature_state):
        reasons.append("feature_freshness_missing")
    elif feature_state != "CURRENT":
        reasons.append("stale_features")
    if expected_move in (None, ""):
        reasons.append("expected_edge_missing")
    elif cost not in (None, "") and as_float(expected_move) is not None and as_float(cost) is not None:
        if float(expected_move) <= float(cost):
            reasons.append("edge_below_cost")
    if symbol and symbol not in as_list(symbol_status.get("paper_symbols")):
        reasons.append("symbol_not_paper_eligible")
    risk_action = risk_status.get("risk_action") or nested_get(paper_status, "current_risk_decision.risk_action")
    if risk_action and str(risk_action).lower() not in {"allow", "approved"}:
        reasons.append("risk_gate_block")
    blockers = as_list(nested_get(canary, "blockers")) + as_list(paper_exec_status.get("paper_filter_blockers"))
    if any("cooldown" in str(item) for item in blockers):
        reasons.append("cooldown_block")
    if any("churn" in str(item) or "flip" in str(item) for item in blockers):
        reasons.append("churn_block")
    if cost in (None, ""):
        reasons.append("missing_cost_model")
    return sorted(set(reasons))


def build_legacy_v2_decision_comparator_status(
    *,
    legacy_status: Mapping[str, Any],
    paper_status: Mapping[str, Any],
    trainer_status: Mapping[str, Any],
    symbol_status: Mapping[str, Any],
    risk_status: Mapping[str, Any],
    paper_exec_status: Mapping[str, Any],
) -> dict[str, Any]:
    legacy_present = _present(legacy_status.get("latest_prediction_id")) or _present(
        legacy_status.get("latest_signal_id")
    )
    v2_prediction_id = nested_get(paper_status, "trainer_prediction.prediction_id") or trainer_status.get(
        "prediction_id"
    )
    v2_present = _present(v2_prediction_id)
    legacy_allow = _legacy_allows(legacy_status)
    v2_allow = _v2_allows(paper_status, risk_status)
    canary = nested_get(paper_status, "current_risk_decision.canary_profile_tightening", {})
    expected_move = nested_get(canary, "expected_move_bps") or paper_exec_status.get(
        "paper_filter_expected_move_bps"
    )
    cost = nested_get(canary, "estimated_cost_bps") or paper_exec_status.get(
        "paper_filter_estimated_cost_bps"
    )
    expected_after_cost = None
    if as_float(expected_move) is not None and as_float(cost) is not None:
        expected_after_cost = float(expected_move) - float(cost)
    comparison_id_source = "|".join(
        [
            str(legacy_status.get("latest_prediction_id") or ""),
            str(v2_prediction_id or ""),
            str(utc_now()),
        ]
    )
    comparison = {
        "comparison_id": "cmp_" + hashlib.sha256(comparison_id_source.encode()).hexdigest()[:16],
        "legacy_prediction_id": legacy_status.get("latest_prediction_id"),
        "legacy_signal_id": legacy_status.get("latest_signal_id"),
        "v2_feature_snapshot_id": nested_get(paper_status, "feature_snapshot.feature_snapshot_id")
        or trainer_status.get("feature_snapshot_id"),
        "v2_prediction_id": v2_prediction_id,
        "symbol": legacy_status.get("latest_symbol")
        or nested_get(paper_status, "trainer_prediction.symbol")
        or paper_exec_status.get("symbol"),
        "side": nested_get(paper_status, "trainer_prediction.raw_output.side")
        or nested_get(paper_status, "current_signal_lineage.signal.side"),
        "timeframe": legacy_status.get("latest_timeframe")
        or nested_get(paper_status, "trainer_prediction.timeframe"),
        "legacy_confidence": legacy_status.get("latest_confidence"),
        "v2_confidence": nested_get(paper_status, "trainer_prediction.confidence_calibrated")
        or trainer_status.get("confidence_calibrated"),
        "v2_confidence_bucket": confidence_bucket(
            nested_get(paper_status, "trainer_prediction.confidence_calibrated")
            or trainer_status.get("confidence_calibrated")
        ),
        "legacy_reason": legacy_status.get("latest_signal_reason"),
        "v2_reason": nested_get(paper_status, "current_risk_decision.risk_reason_code")
        or risk_status.get("risk_reason_code"),
        "v2_block_reason": nested_get(paper_status, "current_risk_decision.canary_profile_tightening.blockers")
        or paper_exec_status.get("paper_filter_blockers")
        or risk_status.get("risk_reason_code"),
        "symbol_scope": {
            "paper_symbols": as_list(symbol_status.get("paper_symbols")),
            "live_symbols": as_list(symbol_status.get("live_symbols")),
        },
        "feature_freshness_state": nested_get(paper_status, "feature_snapshot.freshness_state")
        or nested_get(paper_status, "trainer_prediction.freshness_state"),
        "expected_move_after_cost_bps": expected_after_cost,
        "cost_breakdown_bps": _cost_breakdown(paper_status, paper_exec_status),
        "risk_decision": nested_get(paper_status, "current_risk_decision.risk_action")
        or risk_status.get("risk_action"),
        "comparator_result": _comparison_result(legacy_allow, v2_allow, legacy_present, v2_present),
        "disagreement_reasons": _disagreement_reasons(
            paper_status=paper_status,
            trainer_status=trainer_status,
            symbol_status=symbol_status,
            risk_status=risk_status,
            paper_exec_status=paper_exec_status,
        ),
    }
    status = {
        "worker_id": "legacy_v2_decision_comparator",
        "generated_at": utc_now(),
        "comparison_count": 1,
        "comparisons": [comparison],
        "latest_comparison": comparison,
        "legacy_v2_agreement_status": comparison["comparator_result"],
        "read_only_status": "READ_ONLY_REFERENCE_ONLY",
        "live_gate": LIVE_GATE_STATUS,
        "live_symbols": [],
    }
    status.update(safety_footer())
    return status
