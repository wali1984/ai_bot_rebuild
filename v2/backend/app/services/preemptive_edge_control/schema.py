"""Canonical runtime contract for preemptive edge-control decisions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from v2.backend.app.services.preemptive_edge_control.reasons import (
    ALLOW_ACTIONS,
    PAPER_ONLY_ALLOW_ACTIONS,
    canonical_block_action,
    canonicalize_block_reasons,
)

PREEMPTIVE_DECISION_VERSION = "preemptive_edge_control_runtime_contract_v1"
PREEMPTIVE_SCHEMA_VERSION = PREEMPTIVE_DECISION_VERSION
_OPERATOR_TZ = ZoneInfo("America/New_York")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _et_iso(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        parsed = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        )
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(_OPERATOR_TZ).isoformat(timespec="milliseconds")


def _f(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _first(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _side(candidate: Mapping[str, Any]) -> str | None:
    value = str(_first(candidate.get("side"), candidate.get("action"), candidate.get("selected_action")) or "").lower()
    if value in {"long", "buy"}:
        return "long"
    if value in {"short", "sell"}:
        return "short"
    return None


def _notional(candidate: Mapping[str, Any], decision: Mapping[str, Any]) -> float | None:
    return _f(
        _first(
            decision.get("target_notional_usd"),
            candidate.get("target_notional_usd"),
            candidate.get("gross_notional_usd"),
            candidate.get("notional_usd"),
            candidate.get("notional"),
            candidate.get("notional_usdt"),
        )
    )


def _bps_to_usd(bps: Any, notional: float | None) -> float | None:
    numeric = _f(bps)
    if numeric is None or notional is None:
        return None
    return numeric / 10000.0 * notional


def _guardian_allowed(guardian: Mapping[str, Any] | None) -> bool:
    if not isinstance(guardian, Mapping) or not guardian:
        return False
    status = str(_first(guardian.get("status"), guardian.get("state")) or "").upper()
    if any(token in status for token in ("HALTED", "BLOCKED", "SHADOW_ONLY")):
        return False
    for field in ("guardian_new_entries_allowed", "a_grade_new_entries_allowed", "new_entries_allowed"):
        if field in guardian:
            return guardian.get(field) is True
    return False


def _state_from_score(score: float | None, *, low: float, missing: str, low_state: str, ok: str) -> str:
    if score is None:
        return missing
    if score < low:
        return low_state
    return ok


def canonicalize_preemptive_decision(
    candidate: Mapping[str, Any] | None,
    decision: Mapping[str, Any],
    *,
    continuous_edge_guardian_gate: Mapping[str, Any] | None = None,
    paper_session_id: str | None = None,
) -> dict[str, Any]:
    candidate = candidate if isinstance(candidate, Mapping) else {}
    result = dict(decision)
    reasons = canonicalize_block_reasons(
        list(result.get("preemptive_decision_reasons") or result.get("preemptive_block_reasons") or [])
    )
    loss_probability = _f(result.get("pre_trade_loss_probability"))
    action = canonical_block_action(
        legacy_decision=str(result.get("preemptive_decision") or ""),
        reasons=reasons,
        loss_probability=loss_probability,
    )
    decision_time = str(
        _first(
            result.get("preemptive_decision_time"),
            candidate.get("decision_time"),
            candidate.get("generated_at"),
            candidate.get("signal_generated_at"),
            _utc_now(),
        )
    )
    notional = _notional(candidate, result)
    expected_net = _first(
        result.get("pre_trade_expected_net_pnl_usd"),
        candidate.get("pre_trade_expected_net_pnl_usd"),
        result.get("expected_net_pnl_usd"),
        _bps_to_usd(
            _first(result.get("expected_edge_after_cost_bps"), candidate.get("expected_move_after_cost_bps")),
            notional,
        ),
    )
    expected_gross = _first(
        result.get("pre_trade_expected_gross_pnl_usd"),
        candidate.get("pre_trade_expected_gross_pnl_usd"),
        _bps_to_usd(_first(candidate.get("expected_move_bps"), candidate.get("expected_gross_move_bps")), notional),
        expected_net,
    )
    expected_cost = _first(
        result.get("pre_trade_expected_cost_usd"),
        candidate.get("pre_trade_expected_cost_usd"),
        _bps_to_usd(
            _first(
                result.get("spread_slippage_funding_cost_bps"),
                candidate.get("spread_slippage_funding_cost_bps"),
                (_f(candidate.get("pre_trade_fee_bps")) or 0.0)
                + (_f(candidate.get("expected_slippage_bps")) or 0.0)
                + (_f(candidate.get("funding_bps")) or 0.0),
            ),
            notional,
        ),
    )
    max_loss = _first(
        result.get("pre_trade_max_loss_usd"),
        result.get("max_loss_if_stop_hit"),
        candidate.get("pre_trade_max_loss_usd"),
        candidate.get("max_loss_if_stop_hit"),
        candidate.get("risk_budget_usd"),
        _bps_to_usd(candidate.get("stop_distance_bps"), notional),
    )
    expected_net_f = _f(expected_net)
    max_loss_f = _f(max_loss)
    profit_probability = None if loss_probability is None else round(max(0.0, min(1.0, 1.0 - loss_probability)), 8)
    guardian_allowed = _guardian_allowed(continuous_edge_guardian_gate)
    legacy_decision = str(result.get("preemptive_decision") or "")
    reduce_approved = action == "ALLOW_REDUCE_SIZE_PAPER" and guardian_allowed
    allowed = action in ALLOW_ACTIONS
    result.update(
        {
            "schema_version": PREEMPTIVE_SCHEMA_VERSION,
            "preemptive_decision_version": PREEMPTIVE_DECISION_VERSION,
            "preemptive_decision_time": decision_time,
            "preemptive_decision_time_et": _et_iso(decision_time),
            "candidate_id": _first(candidate.get("candidate_id"), candidate.get("decision_id"), candidate.get("signal_id")),
            "prediction_id": _first(candidate.get("prediction_id"), candidate.get("source_prediction_id")),
            "signal_id": candidate.get("signal_id"),
            "risk_decision_id": candidate.get("risk_decision_id"),
            "orchestrator_decision_id": candidate.get("orchestrator_decision_id"),
            "symbol": candidate.get("symbol"),
            "timeframe": _first(candidate.get("timeframe"), candidate.get("thesis_timeframe")),
            "side": _side(candidate),
            "strategy_id": _first(candidate.get("strategy_id"), candidate.get("strategy_selected_mode"), candidate.get("strategy_mode")),
            "source_tier": candidate.get("source_tier") or candidate.get("paper_opportunity_tier"),
            "strategy_supply_hypothesis": candidate.get("strategy_supply_hypothesis") is True,
            "strategy_supply_hypothesis_id": _first(
                candidate.get("strategy_supply_hypothesis_id"),
                candidate.get("hypothesis_id"),
            ),
            "paper_session_id": _first(paper_session_id, candidate.get("paper_session_id")),
            "pre_trade_expected_net_pnl_usd": expected_net,
            "pre_trade_expected_gross_pnl_usd": expected_gross,
            "pre_trade_expected_cost_usd": expected_cost,
            "pre_trade_max_loss_usd": max_loss,
            "pre_trade_loss_probability": loss_probability,
            "pre_trade_profit_probability": profit_probability,
            "pre_trade_expected_reward_to_risk": (
                None
                if expected_net_f is None or max_loss_f in (None, 0.0)
                else round(expected_net_f / abs(max_loss_f), 8)
            ),
            "pre_trade_liquidation_risk_usd": _first(
                result.get("pre_trade_liquidation_risk_usd"),
                candidate.get("pre_trade_liquidation_risk_usd"),
            ),
            "pre_trade_slippage_risk_usd": _first(
                result.get("pre_trade_slippage_risk_usd"),
                candidate.get("expected_slippage_usd"),
                _bps_to_usd(candidate.get("expected_slippage_bps"), notional),
            ),
            "pre_trade_funding_risk_usd": _first(
                result.get("pre_trade_funding_risk_usd"),
                candidate.get("expected_funding_usd"),
                _bps_to_usd(candidate.get("funding_bps"), notional),
            ),
            "portfolio_pf_window": _first(result.get("portfolio_pf_window"), candidate.get("portfolio_profit_factor")),
            "portfolio_expectancy_usd_window": _first(
                result.get("portfolio_expectancy_usd_window"),
                candidate.get("portfolio_expectancy_usd"),
            ),
            "bucket_pf_window": result.get("bucket_profit_factor"),
            "bucket_expectancy_usd_window": result.get("notional_weighted_bucket_expectancy"),
            "high_confidence_loss_cluster_active": (
                (_f(result.get("recent_high_confidence_loss_rate")) or 0.0) > 0.0
                or any("HIGH_CONFIDENCE_LOSS" in reason for reason in reasons)
            ),
            "atr_stop_cluster_active": (
                (_f(result.get("recent_ATR_stop_risk")) or 0.0) >= 0.40
                or any("ATR_STOP" in reason for reason in reasons)
            ),
            "bucket_quarantine_active": bool(result.get("matched_quarantined_bucket_keys")),
            "microstructure_trust_state": _state_from_score(
                _f(result.get("microstructure_trust_score")),
                low=0.65,
                missing="MISSING",
                low_state="UNSAFE",
                ok="TRUSTED",
            ),
            "fvg_structure_state": _first(result.get("advanced_indicator_status"), "NOT_REPORTED"),
            "liquidity_sweep_state": _state_from_score(
                _f(result.get("liquidity_sweep_risk")),
                low=0.65,
                missing="NOT_REPORTED",
                low_state="LOW_RISK",
                ok="HIGH_RISK",
            ),
            "market_regime_state": _first(candidate.get("market_regime_at_entry"), candidate.get("market_regime"), "UNKNOWN"),
            "guardian_new_entries_allowed": guardian_allowed,
            "continuous_edge_guardian_status": _first(
                continuous_edge_guardian_gate.get("status") if isinstance(continuous_edge_guardian_gate, Mapping) else None,
                continuous_edge_guardian_gate.get("state") if isinstance(continuous_edge_guardian_gate, Mapping) else None,
                "MISSING",
            ),
            "reduce_size_guardian_approved": reduce_approved,
            "reduce_size_guardian_approval_reason": (
                "GUARDIAN_NEW_ENTRIES_ALLOWED"
                if reduce_approved
                else "GUARDIAN_APPROVAL_MISSING_OR_HALTED"
            ),
            "preemptive_action": action,
            "preemptive_allowed": allowed,
            "preemptive_block_reasons": reasons,
            "preemptive_reduce_size_required": action == "ALLOW_REDUCE_SIZE_PAPER",
            "preemptive_shadow_only": action == "SHADOW_ONLY",
            "preemptive_counts_as_a_plus": action == "ALLOW_A_PLUS_CANDIDATE",
            "preemptive_counts_as_live_ready": False,
            "routes_to_live": False,
            "places_real_order": False,
            "allow_paper_fill": allowed,
            "allow_live_dry_run": legacy_decision == "ALLOW" and action == "ALLOW_A_PLUS_CANDIDATE",
            "paper_only": action in PAPER_ONLY_ALLOW_ACTIONS or result.get("paper_only", True) is True,
        }
    )
    result["preemptive_decision_reasons"] = reasons
    return result
