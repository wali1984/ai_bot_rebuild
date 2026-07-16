"""Mobile-optimized compact API endpoints for iOS/iPadOS/watchOS app.

All endpoints are read-only. Live trading actions require human approval
through the web admin interface — no live trade execution from mobile.

Auth: Bearer token via Authorization header (same JWT as web session).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.api.v2._common import get_redis
from app.api.v2.probation_display import probation_gate_display_status
from app.services.realtime.operator_snapshot import _hedge_payload, _ingestors_payload
from app.auth.security import optional_auth, require_auth
from app.auth.users import UserRecord
from app.services.coinglass_provider import build_coinglass_health
from app.services.hedge_engine import compute_portfolio_exposure, simulate_cross_margin_stress
from app.services.portfolio import build_canonical_pnl
from app.services.provider_features import build_provider_actual_data_panel
from app.services.smart_money_wallets import build_moralis_health

router = APIRouter(prefix="/mobile", tags=["v2-mobile"])


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _et_now() -> str:
    return datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _as_list(v: Any) -> list[Any]:
    if isinstance(v, list):
        return v
    if v in (None, ""):
        return []
    return [v]


def _optional_positive_float(v: Any) -> float | None:
    try:
        parsed = float(v)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or abs(parsed) == float("inf"):
        return None
    return parsed if parsed > 0 else None


def _optional_float(v: Any) -> float | None:
    try:
        parsed = float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
    if parsed is None or parsed != parsed or abs(parsed) == float("inf"):
        return None
    return parsed


def _position_quantity(row: dict[str, Any]) -> float:
    fallback = 0.0
    for field in ("qty", "quantity", "net_quantity", "size", "position_size"):
        value = _optional_float(row.get(field))
        if value is None:
            continue
        if abs(value) > 0:
            return value
        fallback = value
    return fallback


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _first_positive_price_with_source(
    row: dict[str, Any],
    fields: list[tuple[str, str]],
) -> tuple[float | None, str | None]:
    for field, source in fields:
        price = _optional_positive_float(row.get(field))
        if price is not None:
            return price, source
    return None, None


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _redis_get_json(r: Any, key: str) -> dict[str, Any] | None:
    try:
        raw = r.get(key)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return None


def _redis_lrange_json(r: Any, key: str, start: int = 0, end: int = -1) -> list[dict[str, Any]]:
    try:
        items = r.lrange(key, start, end)
        return [json.loads(i) for i in items if i]
    except Exception:
        return []


def _dedupe_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if not value:
            continue
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _mobile_a_grade_blocker_truth(r: Any | None) -> dict[str, Any]:
    try:
        from app.api.v2.control_center_status import (  # noqa: PLC0415
            _current_a_grade_blocker_truth,
        )

        return _current_a_grade_blocker_truth(r)
    except Exception:
        return {
            "schema_version": "control_center_a_grade_blocker_truth_v1",
            "status": "A_GRADE_BLOCKER_TRUTH_UNAVAILABLE",
            "available": False,
            "primary_blocker": "A_GRADE_BLOCKER_TRUTH_UNAVAILABLE",
            "finding_ids": [],
            "live_gate": "blocked_human_only",
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            "order_submitted": False,
            "test_order_submitted": False,
            "leverage_mutated": False,
            "margin_mutated": False,
        }


def _mobile_real_trader_readiness(r: Any | None) -> dict[str, Any]:
    blocker_truth = _mobile_a_grade_blocker_truth(r)
    truth_status = str(blocker_truth.get("status") or "")
    finding_ids = blocker_truth.get("finding_ids")
    if not isinstance(finding_ids, list):
        finding_ids = []
    exact_reason = (
        blocker_truth.get("primary_blocker")
        if truth_status == "A_GRADE_ADAPTATION_NOT_PROVEN"
        else None
    )
    if not exact_reason and truth_status != "NO_ACTIVE_BLOCKER_DETECTED":
        exact_reason = truth_status or "A_GRADE_BLOCKER_TRUTH_UNAVAILABLE"
    readiness_blockers = _dedupe_strings([exact_reason, *finding_ids])
    return {
        "live_gate": "blocked_human_only",
        "operator_flip_required": True,
        "order_submitted": False,
        "test_order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
        "routes_to_live": False,
        "places_real_order": False,
        "live_submit_allowed": False,
        "live_ready": False,
        "exact_no_live_reason": exact_reason,
        "readiness_blockers": readiness_blockers,
        "a_grade_blocker_truth": blocker_truth,
    }


def _paper_heartbeat(r: Any) -> dict[str, Any]:
    return _redis_get_json(r, "v2:paper:heartbeat") or {}


def _as_object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _mobile_provider_readiness(r: Any | None) -> dict[str, Any]:
    coinglass = (_redis_get_json(r, "v2:provider:coinglass:health") if r else None) or build_coinglass_health(os.environ)
    moralis = (_redis_get_json(r, "v2:provider:moralis:health") if r else None) or build_moralis_health(os.environ)
    coinglass_usage = (_redis_get_json(r, "v2:provider:coinglass:usage") if r else None) or {}
    moralis_usage = (_redis_get_json(r, "v2:provider:moralis:usage") if r else None) or {}
    coinglass_endpoint_status = (_redis_get_json(r, "v2:provider:coinglass:endpoint_status") if r else None) or {}
    moralis_endpoint_status = (_redis_get_json(r, "v2:provider:moralis:endpoint_status") if r else None) or {}
    provider_actual_data = build_provider_actual_data_panel(
        r,
        symbol=str(os.environ.get("ALPHAFORGE_PROVIDER_PANEL_SYMBOL", "BTCUSDT")).upper(),
        timeframe=str(os.environ.get("ALPHAFORGE_PROVIDER_PANEL_TIMEFRAME", "1m")),
    )
    santiment_status = (_redis_get_json(r, "v2:altdata:santiment:status") if r else None) or {}
    santiment_rate = _as_object(santiment_status.get("rate_limit_state"))
    confluence_sample = (
        _redis_get_json(
            r,
            "v2:altdata:confluence:"
            + str(os.environ.get("ALPHAFORGE_PROVIDER_PANEL_SYMBOL", "BTCUSDT")).upper()
            + ":"
            + str(os.environ.get("ALPHAFORGE_PROVIDER_PANEL_TIMEFRAME", "1m")),
        )
        if r
        else None
    ) or {}
    consumption_status = (
        _redis_get_json(r, "v2:altdata:provider_consumption_status") if r else None
    ) or {}
    return {
        "schema_version": "v2_mobile_provider_readiness_v1",
        "status": "PROVIDER_READINESS_ACTIVE",
        "santiment_status": santiment_status.get("go_no_go"),
        "santiment_symbol_count": santiment_status.get("symbol_count"),
        "santiment_rate_limit_remaining_month": santiment_rate.get("remaining_month"),
        "santiment_rate_limit_month_limit": santiment_rate.get("month_limit"),
        "santiment_regime_only": True,
        "santiment_data_lag_note": "sanbase_pro_31d_lag_regime_layer_only",
        "altdata_confluence_active": bool(confluence_sample.get("actual_payload_present")),
        "altdata_confluence_providers_present": confluence_sample.get("providers_present"),
        "altdata_confluence_feature_cutoff": confluence_sample.get("feature_cutoff"),
        "altdata_trade_block_score": _as_object(confluence_sample.get("features")).get(
            "altdata_trade_block_score"
        ),
        "altdata_reduce_size_score": _as_object(confluence_sample.get("features")).get(
            "altdata_reduce_size_score"
        ),
        "altdata_hedge_required_score": _as_object(confluence_sample.get("features")).get(
            "altdata_hedge_required_score"
        ),
        "altdata_provider_consumption_status": consumption_status,
        "altdata_single_provider_can_approve": False,
        "provider_tensor_consumption": consumption_status.get("provider_tensor_consumption"),
        "provider_risk_consumption": consumption_status.get("provider_risk_consumption"),
        "provider_orchestrator_consumption": consumption_status.get("provider_orchestrator_consumption"),
        "provider_allocator_consumption": consumption_status.get("provider_allocator_consumption"),
        "provider_paper_consumption": consumption_status.get("provider_paper_consumption"),
        "provider_live_dryrun_consumption": consumption_status.get("provider_live_dryrun_consumption"),
        "provider_feedback_attribution": consumption_status.get("provider_feedback_attribution"),
        "ppo_provider_feature_count": consumption_status.get("ppo_provider_feature_count"),
        "masa_provider_feature_count": consumption_status.get("masa_provider_feature_count"),
        "confluence_trade_block_score": consumption_status.get(
            "confluence_trade_block_score",
            _as_object(confluence_sample.get("features")).get("altdata_trade_block_score"),
        ),
        "confluence_reduce_size_score": consumption_status.get(
            "confluence_reduce_size_score",
            _as_object(confluence_sample.get("features")).get("altdata_reduce_size_score"),
        ),
        "confluence_hedge_required_score": consumption_status.get(
            "confluence_hedge_required_score",
            _as_object(confluence_sample.get("features")).get("altdata_hedge_required_score"),
        ),
        "coinglass_status": coinglass.get("status"),
        "moralis_status": moralis.get("status"),
        "coinglass_dashboard_color": provider_actual_data.get("coinglass", {}).get("dashboard_color"),
        "moralis_dashboard_color": provider_actual_data.get("moralis", {}).get("dashboard_color"),
        "coinglass_actual_payload_present": provider_actual_data.get("coinglass", {}).get("actual_payload_present"),
        "moralis_actual_payload_present": provider_actual_data.get("moralis", {}).get("actual_payload_present"),
        "coinglass_heartbeat_only": provider_actual_data.get("coinglass", {}).get("heartbeat_only"),
        "moralis_heartbeat_only": provider_actual_data.get("moralis", {}).get("heartbeat_only"),
        "moralis_feature_bridge_ready": moralis.get("feature_bridge_ready"),
        "moralis_feature_count": moralis.get("feature_count"),
        "moralis_required_feature_count": moralis.get("required_feature_count"),
        "moralis_missing_feature_flags": moralis.get("missing_feature_flags"),
        "moralis_stale_feature_flags": moralis.get("stale_feature_flags"),
        "moralis_missing_mask_true": moralis.get("missing_mask_true"),
        "moralis_stale_mask_true": moralis.get("stale_mask_true"),
        "moralis_token_map_count": moralis.get("token_map_count"),
        "moralis_wallet_watchlist_count": moralis.get("wallet_watchlist_count"),
        "coinglass_usage": coinglass_usage,
        "moralis_usage": moralis_usage,
        "coinglass_endpoint_status": coinglass_endpoint_status,
        "moralis_endpoint_status": moralis_endpoint_status,
        "actual_data_panel": provider_actual_data,
        "coinglass": coinglass,
        "moralis": moralis,
        "raw_keys_exposed": False,
        "invalid_subscription_blocks_core_system": False,
        "optional_provider_failures_core_blocking": False,
        "heartbeat_only_green_allowed": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _mobile_hedge_cross_margin_truth(r: Any | None) -> dict[str, Any]:
    portfolio = (_redis_get_json(r, "v2:portfolio:state") if r else None) or {}
    rows = portfolio.get("positions_by_symbol") or portfolio.get("positions") or []
    positions = [
        row
        for row in rows
        if isinstance(row, dict)
        and row.get("open_position") is not False
        and str(row.get("position_state") or "").lower() != "shadow_observation_only"
    ]
    equity = _safe_float(
        portfolio.get("equity")
        or portfolio.get("current_session_equity")
        or portfolio.get("paper_equity")
    )
    available = _safe_float(portfolio.get("cash_balance") or portfolio.get("available_balance") or equity)
    open_notional = _safe_float(portfolio.get("open_position_notional")) or sum(
        _safe_float(row.get("gross_notional") or row.get("notional") or row.get("notional_usd"))
        for row in positions
    )
    portfolio_summary_leverage = _safe_float(portfolio.get("effective_leverage")) or (
        open_notional / equity if equity > 0 and open_notional > 0 else 0.0
    )
    exposure = compute_portfolio_exposure(positions, equity_usd=equity)
    stress = simulate_cross_margin_stress(
        equity_usd=equity,
        available_margin_usd=available,
        target_notional_usd=open_notional,
        allocated_margin_usd=open_notional,
        recommended_leverage=portfolio_summary_leverage,
        max_loss_usd=portfolio.get("current_drawdown_usd"),
        requested_margin_mode="isolated_paper_simulated",
        expectancy_usd=portfolio.get("session_realized_pnl") or portfolio.get("realized_pnl_usd"),
    )
    # Real hedge truth from position rows — previously hardcoded to
    # NO_HEDGE/0 regardless of the actual v2:portfolio:state contents.
    hedge_rows = sum(
        1
        for row in positions
        if row.get("hedge_state") not in (None, "", "NO_HEDGE")
    )
    hedge_engine_raw = _operator_runtime_json(
        "v2_continuous_edge_guardian/latest/hedge_engine_status.json"
    ) or {}
    hedge_engine_status: dict[str, Any] = {}
    if hedge_engine_raw:
        hedge_engine_status = {
            "status": hedge_engine_raw.get("status"),
            "candidate_count": hedge_engine_raw.get("candidate_count"),
            "accepted_count": hedge_engine_raw.get(
                "accepted_bounded_hedge_candidate_count"
            ),
            "generated_utc": hedge_engine_raw.get("generated_utc"),
        }
    return {
        "schema_version": "v2_mobile_hedge_cross_margin_truth_v1",
        "status": "ADAPTIVE_HEDGE_CROSS_MARGIN_SIMULATION_ACTIVE",
        "paper_session_id": portfolio.get("paper_session_id") or portfolio.get("reset_session_id"),
        "operator_display_currency": "USD",
        "operator_display_timezone": "America/New_York",
        "bps_operator_display_allowed": False,
        "recommended_leverage_distribution": [round(portfolio_summary_leverage, 8)] if open_notional > 0 else [],
        "recommended_margin_mode_distribution": [stress.get("recommended_margin_mode") or "isolated_paper_simulated"] if open_notional > 0 else [],
        "hedge_state": "HEDGE_ROWS_PRESENT" if hedge_rows > 0 else "NO_HEDGE",
        "hedge_rows": hedge_rows,
        "hedge_engine_status": hedge_engine_status,
        "cross_margin_state": stress.get("why_cross_margin_or_isolated"),
        **exposure,
        **stress,
    }


PREEMPTIVE_MATRIX_MOBILE_ROW_LIMIT = 5
PREEMPTIVE_MATRIX_MOBILE_LIST_PREVIEW_LIMIT = 8
PREEMPTIVE_MATRIX_MOBILE_ROW_FIELDS = (
    "preemptive_decision_id",
    "preemptive_decision",
    "preemptive_action",
    "preemptive_allowed",
    "preemptive_shadow_only",
    "preemptive_reduce_size_required",
    "symbol",
    "side",
    "timeframe",
    "strategy_id",
    "source_tier",
    "pre_trade_expected_net_pnl_usd",
    "pre_trade_expected_gross_pnl_usd",
    "pre_trade_expected_cost_usd",
    "pre_trade_max_loss_usd",
    "pre_trade_loss_probability",
    "pre_trade_profit_probability",
    "confidence_overstatement_risk",
    "regime_compatibility_score",
    "exit_feasibility_score",
    "bucket_profit_factor",
    "guardian_new_entries_allowed",
    "continuous_edge_guardian_status",
    "reduce_size_guardian_approved",
    "reduce_size_guardian_approval_reason",
    "advanced_indicator_status",
    "advanced_indicator_confluence_score",
    "fvg_present",
    "fvg_side_aligned",
    "liquidity_sweep_state",
    "microstructure_trust_state",
    "microstructure_trust_score",
    "altdata_confluence_present",
    "altdata_trade_block_score",
    "altdata_reduce_size_score",
    "altdata_hedge_required_score",
    "altdata_wallet_distribution_score",
    "altdata_liquidation_sweep_risk_score",
    "altdata_social_euphoria_risk_score",
    "preemptive_decision_time",
    "preemptive_decision_time_et",
    "paper_session_id",
    "routes_to_live",
    "places_real_order",
)


def _compact_mobile_preemptive_matrix_row(row: dict[str, Any]) -> dict[str, Any]:
    compact = {key: row.get(key) for key in PREEMPTIVE_MATRIX_MOBILE_ROW_FIELDS if key in row}
    for key in (
        "preemptive_block_reasons",
        "preemptive_decision_reasons",
        "advanced_indicator_block_reasons",
        "advanced_indicator_caution_reasons",
        "provider_features_used",
        "provider_features_missing",
        "candidate_bucket_keys",
        "matched_quarantined_bucket_keys",
    ):
        value = row.get(key)
        if not isinstance(value, list):
            continue
        compact[f"{key}_count"] = len(value)
        compact[key] = value[:PREEMPTIVE_MATRIX_MOBILE_LIST_PREVIEW_LIMIT]
        if len(value) > PREEMPTIVE_MATRIX_MOBILE_LIST_PREVIEW_LIMIT:
            compact[f"{key}_omitted_count"] = len(value) - PREEMPTIVE_MATRIX_MOBILE_LIST_PREVIEW_LIMIT
    return compact


def _compact_mobile_preemptive_candidate_decision_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    rows = matrix.get("rows") or matrix.get("sample_decisions") or []
    rows = rows if isinstance(rows, list) else []
    preview_rows = [
        _compact_mobile_preemptive_matrix_row(row)
        for row in rows[:PREEMPTIVE_MATRIX_MOBILE_ROW_LIMIT]
        if isinstance(row, dict)
    ]
    compact = {
        key: value
        for key, value in matrix.items()
        if key not in {"rows", "sample_decisions"}
    }
    compact["rows"] = preview_rows
    compact["sample_decisions"] = preview_rows
    compact["full_row_count"] = len(rows)
    compact["preview_row_count"] = len(preview_rows)
    compact["payload_compacted"] = len(rows) > PREEMPTIVE_MATRIX_MOBILE_ROW_LIMIT
    compact["omitted_row_count"] = max(0, len(rows) - PREEMPTIVE_MATRIX_MOBILE_ROW_LIMIT)
    compact["debug_detail_source"] = "redis:v2:paper:preemptive_candidate_decision_matrix"
    compact.setdefault("paper_only", True)
    compact.setdefault("routes_to_live", False)
    compact.setdefault("places_real_order", False)
    return compact


def _mobile_preemptive_edge_control_truth(r: Any | None) -> dict[str, Any]:
    trade_management_status = (
        _redis_get_json(r, "v2:paper:trade_management:status") if r else None
    ) or {}

    def _contract(key: str, embedded_key: str, fallback: dict[str, Any]) -> dict[str, Any]:
        payload = (_redis_get_json(r, key) if r else None) or _as_object(
            trade_management_status.get(embedded_key)
        )
        if not payload:
            payload = dict(fallback)
        else:
            payload = dict(payload)
            payload.setdefault("available", True)
        payload.setdefault("source", f"redis:{key}")
        payload.setdefault("paper_only", True)
        payload.setdefault("routes_to_live", False)
        payload.setdefault("places_real_order", False)
        return payload

    status = _contract(
        "v2:paper:preemptive_edge_control_status",
        "preemptive_edge_control_status",
        {
            "schema_version": "preemptive_edge_control_status_v1",
            "status": "PREEMPTIVE_EDGE_CONTROL_STATUS_UNAVAILABLE",
            "available": False,
            "candidate_count": 0,
            "accepted_count": 0,
            "decision_counts": {},
            "hard_fail": True,
        },
    )
    matrix = _contract(
        "v2:paper:preemptive_candidate_decision_matrix",
        "preemptive_candidate_decision_matrix",
        {
            "schema_version": "preemptive_candidate_decision_matrix_v1",
            "status": "PREEMPTIVE_CANDIDATE_DECISION_MATRIX_UNAVAILABLE",
            "available": False,
            "candidate_count": 0,
            "sample_decisions": [],
        },
    )
    admission = _contract(
        "v2:paper:preemptive_admission_status",
        "paper_preemptive_admission_status",
        {
            "schema_version": "paper_preemptive_admission_status_v1",
            "status": "PAPER_PREEMPTIVE_ADMISSION_STATUS_UNAVAILABLE",
            "available": False,
            "hard_fail": True,
        },
    )
    probation_policy = _contract(
        "v2:paper:positive_edge_probation_policy",
        "positive_edge_probation_policy",
        {
            "schema_version": "positive_edge_probation_policy_v1",
            "status": "POSITIVE_EDGE_PROBATION_POLICY_UNAVAILABLE",
            "available": False,
            "enabled": False,
        },
    )
    probation_runtime = _contract(
        "v2:paper:positive_edge_probation_runtime_status",
        "positive_edge_probation_runtime_status",
        {
            "schema_version": "positive_edge_probation_runtime_status_v1",
            "status": "POSITIVE_EDGE_PROBATION_RUNTIME_STATUS_UNAVAILABLE",
            "available": False,
            "current_candidate_count": 0,
            "current_accepted_count": 0,
            "closed_probation_trade_count": 0,
            "counts_as_final_a_plus": False,
            "counts_as_live_ready": False,
        },
    )
    probation_5_trade_gate = _contract(
        "v2:paper:probation_5_trade_gate",
        "probation_5_trade_gate",
        {
            "schema_version": "positive_edge_probation_trade_gate_v1",
            "status": "PROBATION_5_TRADE_GATE_WAITING_OR_BLOCKED",
            "available": False,
            "closed_count": 0,
        },
    )
    samples = matrix.get("rows") or matrix.get("sample_decisions")
    samples = samples if isinstance(samples, list) else []
    first_sample = samples[0] if samples and isinstance(samples[0], dict) else {}
    advanced_status_counts: dict[str, int] = {}
    advanced_block_counts: dict[str, int] = {}
    advanced_caution_counts: dict[str, int] = {}
    fvg_present_count = 0
    for row in samples:
        if not isinstance(row, dict):
            continue
        status_text = str(
            row.get("advanced_indicator_status")
            or "ADVANCED_INDICATOR_NOT_REPORTED"
        )
        advanced_status_counts[status_text] = advanced_status_counts.get(status_text, 0) + 1
        if row.get("fvg_present") is True:
            fvg_present_count += 1
        for reason in row.get("advanced_indicator_block_reasons") or []:
            text = str(reason)
            advanced_block_counts[text] = advanced_block_counts.get(text, 0) + 1
        for reason in row.get("advanced_indicator_caution_reasons") or []:
            text = str(reason)
            advanced_caution_counts[text] = advanced_caution_counts.get(text, 0) + 1
    advanced_indicators = {
        "schema_version": "advanced_indicator_runtime_truth_v1",
        "status": (
            "ADVANCED_INDICATOR_DECISION_CONSUMPTION_ACTIVE"
            if samples
            else "ADVANCED_INDICATOR_WAITING_FOR_PREEMPTIVE_MATRIX"
        ),
        "candidate_count": len(samples),
        "status_counts": advanced_status_counts,
        "block_reason_counts": advanced_block_counts,
        "caution_reason_counts": advanced_caution_counts,
        "fvg_present_count": fvg_present_count,
        "accepted_advanced_indicator_block_count": _safe_int(
            admission.get("accepted_advanced_indicator_block_count")
        ),
        "fvg_standalone_allows_trade": False,
        "fvg_alone_can_approve_trade": False,
        "sweep_risk_can_block_or_reduce": True,
        "displayed_without_decision_consumption": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    decision_counts = status.get("decision_counts")
    decision_counts = decision_counts if isinstance(decision_counts, dict) else {}
    action_counts = status.get("action_counts")
    action_counts = action_counts if isinstance(action_counts, dict) else {}
    why_prevented = (
        admission.get("prevention_reasons")
        or admission.get("top_rejection_reasons")
        or first_sample.get("preemptive_decision_reasons")
        or []
    )
    probation_candidate_count = _safe_int(probation_runtime.get("current_candidate_count"))
    probation_supply_state = (
        "NO_SAFE_TRADE_SUPPLY"
        if probation_candidate_count <= 0
        else "POSITIVE_EDGE_PROBATION_SUPPLY_AVAILABLE"
    )
    probation_5_display_status = probation_gate_display_status(probation_5_trade_gate)
    return {
        "preemptive_edge_control": {
            "status": (
                "PREEMPTIVE_EDGE_CONTROL_ACTIVE"
                if status.get("available") is True
                else "PREEMPTIVE_EDGE_CONTROL_NOT_YET_PUBLISHED"
            ),
            "candidate_count": _safe_int(status.get("candidate_count")),
            "accepted_count": _safe_int(status.get("accepted_count")),
            "decision_counts": decision_counts,
            "action_counts": action_counts,
            "preemptive_decision_id": first_sample.get("preemptive_decision_id"),
            "preemptive_action": first_sample.get("preemptive_action"),
            "preemptive_allowed": first_sample.get("preemptive_allowed") is True,
            "preemptive_block_reasons": (
                first_sample.get("preemptive_block_reasons")
                or first_sample.get("preemptive_decision_reasons")
                or []
            ),
            "pre_trade_expected_net_pnl_usd": _optional_float(
                first_sample.get("pre_trade_expected_net_pnl_usd")
            ),
            "pre_trade_loss_probability": _optional_float(
                first_sample.get("pre_trade_loss_probability")
            ),
            "guardian_new_entries_allowed": (
                first_sample.get("guardian_new_entries_allowed") is True
            ),
            "continuous_edge_guardian_status": first_sample.get(
                "continuous_edge_guardian_status"
            ),
            "reduce_size_guardian_approved": (
                first_sample.get("reduce_size_guardian_approved") is True
            ),
            "confidence_overstatement_risk": _optional_float(
                first_sample.get("confidence_overstatement_risk")
            ),
            "regime_compatibility_score": _optional_float(
                first_sample.get("regime_compatibility_score")
            ),
            "exit_feasibility_score": _optional_float(
                first_sample.get("exit_feasibility_score")
            ),
            "bucket_profit_factor": _optional_float(
                first_sample.get("bucket_profit_factor")
            ),
            "positive_edge_probation_status": probation_runtime.get("status"),
            "positive_edge_probation_supply_state": probation_supply_state,
            "positive_edge_probation_candidates": probation_candidate_count,
            "positive_edge_probation_accepted": _safe_int(
                probation_runtime.get("current_accepted_count")
            ),
            "closed_probation_trade_count": _safe_int(
                probation_runtime.get("closed_probation_trade_count")
            ),
            "probation_5_trade_gate_status": probation_5_display_status,
            "probation_counts_as_final_a_plus": False,
            "probation_counts_as_live_ready": False,
            "why_trade_was_prevented": why_prevented if isinstance(why_prevented, list) else [],
            "governor_auto_action": (
                "halt_new_entries"
                if decision_counts.get("NO_TRADE") or decision_counts.get("SHADOW_ONLY")
                else "evaluate_preemptive_candidate"
            ),
            "next_remediation": (
                "Wait for governor clearance and post-patch recovery evidence"
                if status.get("accepted_count") in (None, 0)
                else "Verify accepted rows keep loss probability below the bound"
            ),
            "hard_fail": status.get("hard_fail") is True,
            "advanced_indicators": advanced_indicators,
            "advanced_indicator_status": advanced_indicators["status"],
            "advanced_indicator_block_reason_counts": advanced_block_counts,
            "advanced_indicator_caution_reason_counts": advanced_caution_counts,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        },
        "advanced_indicators": advanced_indicators,
        "adaptive_hedge_cross_margin": _mobile_hedge_cross_margin_truth(r),
        "provider_readiness": _mobile_provider_readiness(r),
        "preemptive_edge_control_status": status,
        "preemptive_candidate_decision_matrix": _compact_mobile_preemptive_candidate_decision_matrix(matrix),
        "paper_preemptive_admission_status": admission,
        "positive_edge_probation_policy": probation_policy,
        "positive_edge_probation_runtime_status": probation_runtime,
        "probation_5_trade_gate": probation_5_trade_gate,
    }


def _mobile_preemptive_edge_control_summary(r: Any | None) -> dict[str, Any]:
    status = (_redis_get_json(r, "v2:paper:preemptive_edge_control_status") if r else None) or {}
    admission = (_redis_get_json(r, "v2:paper:preemptive_admission_status") if r else None) or {}
    probation_runtime = (_redis_get_json(r, "v2:paper:positive_edge_probation_runtime_status") if r else None) or {}
    probation_gate = (_redis_get_json(r, "v2:paper:probation_5_trade_gate") if r else None) or {}
    decision_counts = status.get("decision_counts") if isinstance(status.get("decision_counts"), dict) else {}
    action_counts = status.get("action_counts") if isinstance(status.get("action_counts"), dict) else {}
    prevention_reasons = admission.get("prevention_reasons") or admission.get("top_rejection_reasons") or []
    probation_candidate_count = _safe_int(probation_runtime.get("current_candidate_count"))
    return {
        "preemptive_edge_control": {
            "status": (
                "PREEMPTIVE_EDGE_CONTROL_ACTIVE"
                if status.get("available") is True or bool(status)
                else "PREEMPTIVE_EDGE_CONTROL_NOT_YET_PUBLISHED"
            ),
            "candidate_count": _safe_int(status.get("candidate_count")),
            "accepted_count": _safe_int(status.get("accepted_count")),
            "decision_counts": dict(list(decision_counts.items())[:8]),
            "action_counts": dict(list(action_counts.items())[:8]),
            "positive_edge_probation_status": probation_runtime.get("status"),
            "positive_edge_probation_supply_state": (
                "NO_SAFE_TRADE_SUPPLY"
                if probation_candidate_count <= 0
                else "POSITIVE_EDGE_PROBATION_SUPPLY_AVAILABLE"
            ),
            "positive_edge_probation_candidates": probation_candidate_count,
            "positive_edge_probation_accepted": _safe_int(probation_runtime.get("current_accepted_count")),
            "closed_probation_trade_count": _safe_int(probation_runtime.get("closed_probation_trade_count")),
            "probation_5_trade_gate_status": probation_gate_display_status(probation_gate),
            "why_trade_was_prevented": prevention_reasons[:6] if isinstance(prevention_reasons, list) else [],
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        },
        "adaptive_hedge_cross_margin": _mobile_hedge_cross_margin_truth(r),
        "provider_readiness": _mobile_provider_readiness(r),
    }


def _mobile_a_plus_runtime_summary(r: Any | None) -> dict[str, Any]:
    governor = (_redis_get_json(r, "v2:paper:performance_governor_status") if r else None) or {}
    halt = (_redis_get_json(r, "v2:paper:new_entry_emergency_halt_status") if r else None) or {}
    freeze = (_redis_get_json(r, "v2:paper:entry_freeze") if r else None) or {}
    a_plus = (_redis_get_json(r, "v2:paper:a_plus_gate:status") if r else None) or {}
    trainer = (_redis_get_json(r, "v2:trainer:hybrid_cuda:status") if r else None) or {}
    market_hb = (_redis_get_json(r, "v2:market:coinapi:ohlcv:heartbeat") if r else None) or {}
    closed_count = _safe_int(governor.get("closed_outcome_count")) or 0
    realized_pnl_usd = _safe_float(governor.get("realized_pnl_usd"))
    top_blockers = list((freeze.get("future_gate_blockers") or []))
    for reason in (halt.get("halt_reasons") or []):
        if reason not in top_blockers:
            top_blockers.append(reason)
    market_generated_at = (
        market_hb.get("finished_utc")
        or market_hb.get("generated_at")
        or market_hb.get("generated_utc")
        or market_hb.get("ts")
    )
    market_age_seconds: int | None = None
    if isinstance(market_generated_at, str) and market_generated_at:
        try:
            parsed = datetime.fromisoformat(market_generated_at.replace("Z", "+00:00"))
            market_age_seconds = max(0, int((datetime.now(UTC) - parsed.astimezone(UTC)).total_seconds()))
        except ValueError:
            market_age_seconds = None
    real_trader_readiness = _mobile_real_trader_readiness(r)
    readiness_blockers = real_trader_readiness.get("readiness_blockers")
    if not isinstance(readiness_blockers, list):
        readiness_blockers = []
    top_blockers = _dedupe_strings([*readiness_blockers, *top_blockers])
    return {
        "performance": {
            "profit_factor": governor.get("profit_factor"),
            "expectancy_usd": (
                round(realized_pnl_usd / max(1, closed_count), 8)
                if realized_pnl_usd is not None and closed_count
                else None
            ),
            "realized_pnl_usd": realized_pnl_usd,
            "notional_weighted_expectancy_bps": governor.get("notional_weighted_expectancy_bps"),
            "win_rate": governor.get("win_rate"),
            "closed_outcome_count": governor.get("closed_outcome_count"),
            "governor_state": governor.get("state"),
        },
        "entry_freeze": {
            "new_entries_allowed": halt.get("new_entries_allowed"),
            "halt_reasons": (halt.get("halt_reasons") or [])[:6],
            "future_gate_blockers": (freeze.get("future_gate_blockers") or [])[:6],
            "allow_close": halt.get("allow_close"),
            "allow_reduce": halt.get("allow_reduce"),
        },
        "a_plus_gate": {
            "evaluated_candidates": a_plus.get("evaluated_candidates"),
            "a_plus_candidates": a_plus.get("a_plus_candidates"),
            "rejected_reason_matrix": dict(list((a_plus.get("rejected_reason_matrix") or {}).items())[:8])
            if isinstance(a_plus.get("rejected_reason_matrix"), dict) else None,
            "gate_is_hard_entry_condition": a_plus.get("gate_is_hard_entry_condition"),
        },
        "trainer_learning": {
            "effective_trainer_mode": trainer.get("effective_trainer_mode"),
            "online_learning_status": trainer.get("online_learning_status"),
            "last_successful_weight_update_at": trainer.get("last_successful_weight_update_at"),
            "checkpoint_id": trainer.get("checkpoint_id"),
        },
        "real_trader_readiness": real_trader_readiness,
        "market_data_freshness": {
            "source": market_hb.get("source") or "v2:market:coinapi:ohlcv:heartbeat",
            "generated_at": market_generated_at,
            "age_seconds": market_age_seconds,
            "freshness_state": (
                "MARKET_FEED_CURRENT"
                if market_age_seconds is not None and market_age_seconds < 600
                else "MARKET_FEED_STALE"
            ),
        },
        **_mobile_preemptive_edge_control_summary(r),
        "top_blockers": top_blockers[:6],
    }


def _operator_runtime_json(relative: str) -> dict[str, Any] | None:
    operator_runtime_dir = os.getenv("V2_OPERATOR_RUNTIME_STATIC_DIR")
    candidates: list[Path] = []
    if operator_runtime_dir:
        candidates.append(Path(operator_runtime_dir) / relative)
    candidates.append(Path("v2/frontend/public/operator_runtime") / relative)
    try:
        candidates.append(
            Path(__file__).resolve().parents[4]
            / "frontend"
            / "public"
            / "operator_runtime"
            / relative
        )
    except IndexError:
        pass
    for candidate in candidates:
        try:
            if candidate.exists():
                data = json.loads(candidate.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else None
        except Exception:
            continue
    return None


def _first_int(*values: Any, default: int = 0) -> int:
    for value in values:
        if value is None or value == "":
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return default


def _project_fields(payload: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: payload.get(field) for field in fields if field in payload}


def _mobile_runtime_truth_from_redis(
    r: Any | None,
    hb: dict[str, Any],
) -> dict[str, Any]:
    trade_management_status = (
        _redis_get_json(r, "v2:paper:trade_management:status") if r else None
    ) or {}
    runtime_admission_status = _as_object(
        trade_management_status.get("paper_runtime_admission_status")
    )
    runtime_cost_status = _as_object(
        trade_management_status.get("paper_runtime_cost_capture_status")
    )

    a_grade_status = (
        _redis_get_json(r, "v2:paper:a_grade_gate_burndown_status") if r else None
    ) or _as_object(trade_management_status.get("paper_a_grade_gate_burndown_status"))
    forward_canary_status = (
        _redis_get_json(r, "v2:paper:forward_canary_evidence_status") if r else None
    ) or _as_object(
        trade_management_status.get("paper_forward_canary_evidence_status")
    ) or _as_object(hb.get("paper_forward_canary_evidence_status"))

    a_grade_predicates = _as_object(a_grade_status.get("predicate_counts"))
    intent_rows = _first_int(
        runtime_cost_status.get("paper_intent_rows"),
        runtime_admission_status.get("intents_built"),
        a_grade_status.get("prediction_rows"),
    )
    order_applicable_rows = _first_int(
        runtime_cost_status.get("order_cost_applicable_rows"),
        intent_rows,
    )
    production_grade_cost_rows = _first_int(
        runtime_cost_status.get("production_grade_cost_rows"),
        a_grade_status.get("production_grade_cost_rows"),
        a_grade_predicates.get("production_grade_cost_rows"),
    )
    production_grade_cost_order_applicable_rows = _first_int(
        runtime_cost_status.get("production_grade_cost_order_applicable_rows"),
        min(production_grade_cost_rows, order_applicable_rows),
    )
    production_grade_cost_total_row_coverage = _optional_float(
        runtime_cost_status.get("production_grade_cost_total_row_coverage")
    )
    if production_grade_cost_total_row_coverage is None:
        production_grade_cost_total_row_coverage = (
            production_grade_cost_rows / intent_rows if intent_rows else 0.0
        )
    production_grade_cost_coverage = _optional_float(
        runtime_cost_status.get("production_grade_cost_coverage")
    )
    if production_grade_cost_coverage is None:
        production_grade_cost_coverage = (
            production_grade_cost_order_applicable_rows / order_applicable_rows
            if order_applicable_rows
            else 0.0
        )

    if a_grade_status:
        a_grade_status = dict(a_grade_status)
        a_grade_status.setdefault("source", "redis:v2:paper:a_grade_gate_burndown_status")
        a_grade_status.setdefault("available", True)
        a_grade_rows = _first_int(
            a_grade_status.get("A_grade_rows"),
            a_grade_status.get("a_grade_rows"),
        )
        near_a_grade_rows = _first_int(
            a_grade_status.get("near_A_grade_rows"),
            a_grade_status.get("near_a_grade_rows"),
        )
        a_grade_status["A_grade_rows"] = a_grade_rows
        a_grade_status["a_grade_rows"] = a_grade_rows
        a_grade_status["near_A_grade_rows"] = near_a_grade_rows
        a_grade_status["near_a_grade_rows"] = near_a_grade_rows
    else:
        a_grade_status = {
            "schema_version": "paper_a_grade_gate_burndown_status_v1",
            "status": "A_GRADE_GATE_BURNDOWN_STATUS_UNAVAILABLE",
            "source": "redis:v2:paper:a_grade_gate_burndown_status",
            "available": False,
            "A_grade_rows": 0,
            "a_grade_rows": 0,
            "near_A_grade_rows": 0,
            "near_a_grade_rows": 0,
        }

    if forward_canary_status:
        forward_canary_status = dict(forward_canary_status)
        forward_canary_status.setdefault(
            "source", "redis:v2:paper:forward_canary_evidence_status"
        )
        forward_canary_status.setdefault("available", True)
    else:
        forward_canary_status = {
            "schema_version": "paper_forward_canary_evidence_status_v1",
            "status": "FORWARD_CANARY_EVIDENCE_STATUS_UNAVAILABLE",
            "source": "redis:v2:paper:forward_canary_evidence_status",
            "available": False,
            "counts_as_a_grade_evidence": False,
            "valid_forward_canary_economic_outcomes": 0,
            "post_cutover_valid_forward_canary_economic_outcomes": 0,
        }

    trajectory_rel = "v2_continuous_edge_guardian/latest/one_thousand_x_trajectory_status.json"
    trajectory_status = _operator_runtime_json(trajectory_rel) or {}
    if trajectory_status:
        trajectory_status = dict(trajectory_status)
        trajectory_status.setdefault("source", f"operator_runtime/{trajectory_rel}")
        trajectory_status.setdefault("available", True)
        trajectory_status.setdefault("guaranteed_profit_claim", False)
        trajectory_status.setdefault("leverage_increase_allowed_because_behind", False)
    else:
        trajectory_status = {
            "schema_version": "one_thousand_x_trajectory_status_v1",
            "status": "ONE_THOUSAND_X_TRAJECTORY_STATUS_UNAVAILABLE",
            "current_status": "ONE_THOUSAND_X_TRAJECTORY_STATUS_UNAVAILABLE",
            "trajectory_status": "ONE_THOUSAND_X_TRAJECTORY_STATUS_UNAVAILABLE",
            "source": f"operator_runtime/{trajectory_rel}",
            "available": False,
            "guaranteed_profit_claim": False,
            "leverage_increase_allowed_because_behind": False,
        }

    return {
        "production_grade_cost_rows": production_grade_cost_rows,
        "production_grade_cost_order_applicable_rows": (
            production_grade_cost_order_applicable_rows
        ),
        "production_grade_cost_coverage": production_grade_cost_coverage,
        "production_grade_cost_total_row_coverage": (
            production_grade_cost_total_row_coverage
        ),
        "production_grade_cost_coverage_basis": str(
            runtime_cost_status.get("production_grade_cost_coverage_basis") or ""
        ),
        "unexplained_missing_cost_rows": _first_int(
            runtime_cost_status.get("unexplained_missing_cost_rows")
        ),
        "routes_to_live_rows": _first_int(runtime_cost_status.get("routes_to_live_rows")),
        "places_real_order_rows": _first_int(
            runtime_cost_status.get("places_real_order_rows")
        ),
        "paper_runtime_cost_capture_status": _project_fields(
            {
                **runtime_cost_status,
                "production_grade_cost_coverage": production_grade_cost_coverage,
                "production_grade_cost_total_row_coverage": (
                    production_grade_cost_total_row_coverage
                ),
            },
            (
                "schema_version",
                "source",
                "paper_intent_rows",
                "order_cost_applicable_rows",
                "production_grade_cost_rows",
                "production_grade_cost_order_applicable_rows",
                "production_grade_cost_coverage",
                "production_grade_cost_coverage_basis",
                "production_grade_cost_total_row_coverage",
                "unexplained_missing_cost_rows",
                "no_order_missing_cost_rows",
                "paper_fill_allowed_rows",
                "routes_to_live_rows",
                "places_real_order_rows",
                "paper_only",
                "routes_to_live",
                "places_real_order",
            ),
        ),
        "paper_a_grade_gate_burndown_status": _project_fields(
            a_grade_status,
            (
                "schema_version",
                "source",
                "available",
                "generated_utc",
                "status",
                "A_grade_rows",
                "a_grade_rows",
                "near_A_grade_rows",
                "near_a_grade_rows",
                "closest_gap_reason",
                "root_cause_counts",
                "predicate_counts",
                "dominant_current_runtime_reasons",
                "source_rows",
                "pass_conditions",
                "guardian_status",
                "guardian_new_entries_allowed",
                "guardian_block_all_new_a_grade_entries",
            ),
        ),
        "paper_forward_canary_evidence_status": _project_fields(
            forward_canary_status,
            (
                "schema_version",
                "source",
                "available",
                "generated_utc",
                "status",
                "valid_forward_canary_economic_outcomes",
                "post_cutover_valid_forward_canary_economic_outcomes",
                "required_forward_canary_economic_outcomes",
                "valid_symbol_count",
                "required_symbol_count",
                "valid_side_counts",
                "side_counts",
                "forward_canary_shortfalls",
                "failed_forward_canary_blocker_details",
                "production_grade_cost_coverage",
                "pass_conditions",
                "non_counting_reasons",
                "counts_as_a_grade_evidence",
                "paper_only",
                "routes_to_live",
                "places_real_order",
            ),
        ),
        "one_thousand_x_trajectory_runtime_status": _project_fields(
            trajectory_status,
            (
                "schema_version",
                "source",
                "available",
                "generated_utc",
                "status",
                "current_status",
                "trajectory_status",
                "blocker",
                "trajectory_status_detail",
                "calibration_status",
                "target_multiple",
                "target_horizon_days",
                "required_daily_return_pct",
                "required_daily_geometric_return",
                "required_monthly_geometric_return",
                "actual_1d_return",
                "actual_7d_return",
                "actual_30d_return",
                "drawdown_adjusted_growth_rate",
                "lower_confidence_bound_growth_rate",
                "days_ahead_or_behind_target",
                "projection_days",
                "A_plus_rows",
                "B_grade_rows",
                "current_A_plus_daily_return_pct",
                "current_B_grade_daily_return_pct",
                "current_actual_daily_return_pct",
                "B_grade_counts_as_1000x_proof",
                "required_operator_text",
                "required_edge",
                "required_capital",
                "guaranteed_profit_claim",
                "leverage_increase_allowed_because_behind",
            ),
        ),
        **_mobile_preemptive_edge_control_truth(r),
    }


def _trainer_status_from_redis(r: Any) -> dict[str, Any]:
    """Read trainer status from v2:trainer:hybrid_cuda:metrics (real data)."""
    metrics = _redis_get_json(r, "v2:trainer:hybrid_cuda:metrics") or {}
    heartbeat = _redis_get_json(r, "v2:trainer:hybrid_cuda:heartbeat") or {}
    runtime_status = _redis_get_json(r, "v2:trainer:hybrid_cuda:status") or {}
    champion_challenger = _redis_get_json(r, "v2:trainer:champion_challenger_status") or {
        "status": "MISSING_RUNTIME_EVIDENCE",
        "available": False,
        "best_challenger_id": None,
        "promotion_allowed": False,
        "promotion_reason": "runtime key missing",
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    if isinstance(champion_challenger, dict):
        champion_challenger = {
            **champion_challenger,
            "available": champion_challenger.get("available", True),
            "promotion_allowed": champion_challenger.get("promotion_allowed") is True,
            "routes_to_live": champion_challenger.get("routes_to_live") is True,
            "places_real_order": champion_challenger.get("places_real_order") is True,
        }
    training = metrics.get("training") or {}
    cpu_util = metrics.get("cuda_cpu_resource_utilization") or {}
    checkpoint_data = metrics.get("checkpoint") or {}
    inner_metrics = training.get("metrics") or {}

    # Derive trainer state
    effective_mode = inner_metrics.get("effective_trainer_mode") or ""
    trainer_source = heartbeat.get("trainer_source") or ""
    if effective_mode:
        state = effective_mode
    elif trainer_source:
        state = trainer_source.replace("V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_", "").replace("_", " ")
    else:
        state = "UNKNOWN"

    cuda_active = bool(training.get("cuda_active") or cpu_util.get("cuda_available"))
    gpu_name = training.get("gpu_name") or cpu_util.get("gpu_name") or ""
    device = training.get("device") or ""
    checkpoint_id = checkpoint_data.get("checkpoint_id") or ""
    checkpoint_source = checkpoint_data.get("checkpoint_source") or ""

    steps_total = _safe_int(inner_metrics.get("optimizer_steps_total"))
    tpm = _safe_float(cpu_util.get("training_steps_per_minute"))
    steps_last_hour = int(tpm * 60) if tpm > 0 else 0

    data_cov = _safe_float(metrics.get("data_coverage_avg"))

    # Model-identity truths (WI-1 temporal era) from the runtime status key.
    arch = runtime_status.get("model_architecture") or {}
    input_dim = runtime_status.get("input_dim") or arch.get("input_dim")
    feature_count = runtime_status.get("feature_dim")

    # Online-learning + model-edge + throughput truths from the runtime status key
    # so the iOS trainer/AI screens can surface the same telemetry the web AI page
    # shows (read-only; never approves live).
    backtest = cpu_util.get("policy_backtest") or {}
    learning_metrics = runtime_status.get("learning_metrics") or {}
    online_learning_status = runtime_status.get("online_learning_status") or ""
    effective_trainer_mode = runtime_status.get("effective_trainer_mode") or effective_mode or ""
    weights_updating = str(online_learning_status).upper() == "WEIGHTS_UPDATING"

    return {
        "state": state,
        "checkpoint": checkpoint_id,
        "model_source": checkpoint_source,
        "cuda_active": cuda_active,
        "device": device,
        "gpu_name": gpu_name,
        "data_coverage": data_cov,
        "training_steps_total": steps_total,
        "training_steps_last_hour": steps_last_hour,
        "champion_challenger_status": champion_challenger,
        "model_id": runtime_status.get("model_id") or "",
        "input_dim": _safe_int(input_dim) if input_dim is not None else None,
        "feature_count": _safe_int(feature_count) if feature_count is not None else None,
        "temporal_encoder": (arch.get("temporal_encoder") or "") if isinstance(arch, dict) else "",
        "temporal_encoder_enabled": bool(arch.get("temporal_encoder_enabled")) if isinstance(arch, dict) else False,
        "effective_trainer_mode": effective_trainer_mode,
        "online_learning_status": online_learning_status,
        "weights_updating": weights_updating,
        "trainer_process_status": runtime_status.get("trainer_process_status") or "",
        "backtest_win_rate": _safe_float(backtest.get("win_rate")) if backtest.get("win_rate") is not None else None,
        "backtest_expectancy_bps": _safe_float(backtest.get("expectancy_after_cost_bps")) if backtest.get("expectancy_after_cost_bps") is not None else None,
        "backtest_profit_factor": _safe_float(backtest.get("profit_factor_proxy")) if backtest.get("profit_factor_proxy") is not None else None,
        "throughput_predictions_per_second": _safe_float(cpu_util.get("throughput_predictions_per_second")) if cpu_util.get("throughput_predictions_per_second") is not None else None,
        "vram_used_mb": _safe_float(cpu_util.get("current_vram_used_mb")) if cpu_util.get("current_vram_used_mb") is not None else None,
        "generalization_gap": _safe_float(learning_metrics.get("train_val_generalization_gap")) if learning_metrics.get("train_val_generalization_gap") is not None else None,
        "validation_loss_delta": _safe_float(learning_metrics.get("validation_loss_delta")) if learning_metrics.get("validation_loss_delta") is not None else None,
    }


def _gpu_status_from_redis(r: Any) -> dict[str, Any]:
    """Read GPU status from v2:trainer:hybrid_cuda:metrics."""
    metrics = _redis_get_json(r, "v2:trainer:hybrid_cuda:metrics") or {}
    training = metrics.get("training") or {}
    cpu_util = metrics.get("cuda_cpu_resource_utilization") or {}

    name = training.get("gpu_name") or cpu_util.get("gpu_name") or ""
    vram_used = _safe_float(training.get("vram_allocated_mb") or cpu_util.get("current_vram_used_mb"))
    vram_total = _safe_float(cpu_util.get("vram_target_mb") or cpu_util.get("vram_reserved_mb"))
    util_pct = _safe_float(cpu_util.get("current_gpu_utilization"))
    device = training.get("device") or ""
    temp = _safe_float(cpu_util.get("temperature_c"))

    return {
        "name": name,
        "device": device,
        "utilization_pct": util_pct,
        "vram_used_mb": int(vram_used),
        "vram_total_mb": int(vram_total),
        "temperature_c": temp,
    }



def _signal_latest_keys(r: Any) -> list[str]:
    """Bounded signal-key list derived from the runtime symbol universe.

    NEVER glob-SCAN v2:signals:latest:* here: the shared Redis holds >1.5M keys
    and a full keyspace walk takes 10-30s, hanging the mobile endpoints.
    """
    try:
        from app.services.v2_symbol_runtime_universe import resolve_symbols  # noqa: PLC0415

        symbols = resolve_symbols(explicit=None, smoke_test=False)
    except Exception:
        symbols = []
    keys = [f"v2:signals:latest:{symbol}" for symbol in symbols]
    if not keys:
        return []
    try:
        with r.pipeline(transaction=False) as pipe:
            for key in keys:
                pipe.exists(key)
            flags = pipe.execute()
        return [key for key, flag in zip(keys, flags) if flag]
    except Exception:
        return []


def _signal_matrix_from_redis(r: Any, limit: int = 150) -> list[dict[str, Any]]:
    """Scan v2:signals:latest:* (per-symbol keys) and return sorted list."""
    rows: list[dict[str, Any]] = []
    try:
        # Bounded, universe-derived key list (no keyspace scan on 1.5M+ keys).
        keys: list[str] = _signal_latest_keys(r)
        if keys:
            with r.pipeline(transaction=False) as pipe:
                for k in keys:
                    pipe.get(k)
                values = pipe.execute()
            for raw in values:
                if raw:
                    try:
                        rows.append(json.loads(raw))
                    except Exception:
                        pass
    except Exception:
        pass
    # Sort by confidence descending — show most confident first
    rows.sort(key=lambda x: _safe_float(x.get("confidence")), reverse=True)
    return rows[:limit]


def _paper_positions_from_redis(r: Any) -> list[dict[str, Any]]:
    try:
        raw = r.get("v2:paper:positions")
        if raw:
            data = json.loads(raw)
            if isinstance(data, dict):
                data = list(data.values())
            return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []
    except Exception:
        pass
    return []


def _paper_closed_trades_from_redis(r: Any) -> list[dict[str, Any]]:
    try:
        raw = r.get("v2:paper:closed_trades")
        if raw:
            data = json.loads(raw)
            if isinstance(data, dict):
                data = list(data.values())
            return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []
    except Exception:
        pass
    return []


def _mobile_paper_charts(r: Any, max_points: int = 60) -> dict[str, Any]:
    """Compact cumulative-equity curve + win/loss for the mobile dashboard charts.

    Reads the same v2:paper:closed_trades ledger the web uses so the iOS app can
    draw a real equity trend + win/loss donut instead of scalar tiles only.
    """
    rows = _paper_closed_trades_from_redis(r)
    if not rows:
        return {"equity_curve": [], "win_rate": None, "win_count": 0, "loss_count": 0}
    ordered = sorted(rows, key=lambda x: str(x.get("exit_price_utc") or x.get("closed_at") or ""))
    cumulative = 0.0
    curve: list[dict[str, Any]] = []
    wins = losses = 0
    for row in ordered:
        pnl = _safe_float(row.get("realized_pnl_usd"))
        if pnl is None:
            pnl = _safe_float(row.get("realized_pnl")) or 0.0
        cumulative += pnl
        if pnl > 0:
            wins += 1
        elif pnl < 0:
            losses += 1
        curve.append({"t": row.get("exit_price_utc"), "cumulative_pnl": round(cumulative, 4), "pnl": round(pnl, 4)})
    total = wins + losses
    return {
        "equity_curve": curve[-max_points:],
        "win_rate": round(wins / total, 4) if total else None,
        "win_count": wins,
        "loss_count": losses,
    }


def _recent_closed_trade_rows(rows: list[dict[str, Any]], limit: int = 200) -> list[dict[str, Any]]:
    projected = [row for row in rows if isinstance(row, dict)]
    projected.sort(
        key=lambda row: str(
            row.get("closed_at")
            or row.get("exit_price_utc")
            or row.get("closed_utc")
            or row.get("generated_at")
            or row.get("generated_utc")
            or ""
        ),
        reverse=True,
    )
    return projected[:limit]


def _alerts_from_redis(r: Any, limit: int = 30) -> list[dict[str, Any]]:
    return _redis_lrange_json(r, "v2:market:alerts", 0, limit - 1)


def _risk_status_from_redis(r: Any) -> dict[str, Any]:
    """Read risk status from v2:risk:gateway:heartbeat (real data)."""
    gw = _redis_get_json(r, "v2:risk:gateway:heartbeat") or {}
    governor = _redis_get_json(r, "v2:paper:performance_governor_status") or {}
    closed_count = _safe_int(governor.get("closed_outcome_count")) or 0
    realized_pnl_usd = _safe_float(governor.get("realized_pnl_usd"))
    governor_state = (
        governor.get("state")
        or governor.get("status")
        or governor.get("governor_state")
    )
    return {
        "state": governor_state or gw.get("current_gate_state") or gw.get("classification") or "FAIL_CLOSED_NO_RECENT_RISK_RECORDS",
        "classification": gw.get("classification") or "",
        "kill_switch_active": bool(gw.get("live_blocked", True)),
        "fail_closed": bool(gw.get("fail_closed", True)),
        "new_entries_allowed": governor.get("new_entries_allowed"),
        "profit_factor": _safe_float(governor.get("profit_factor")),
        "expectancy_usd": (
            round(realized_pnl_usd / max(1, closed_count), 8)
            if realized_pnl_usd is not None and closed_count
            else None
        ),
        "realized_pnl_usd": realized_pnl_usd,
        "expectancy_bps": _safe_float(
            governor.get("notional_weighted_expectancy_bps")
            or governor.get("expectancy_bps")
            or governor.get("expectancy")
        ),
        "decisions_processed_total": _safe_int(gw.get("decisions_processed_total")),
        "max_position_size_usd": _safe_float(gw.get("max_position_size_usd")),
        "daily_loss_limit_usd": _safe_float(gw.get("daily_loss_limit_usd")),
        "current_daily_loss_usd": _safe_float(gw.get("current_daily_loss_usd")),
    }


def _live_gate_status() -> dict[str, Any]:
    return {
        "live_trading_enabled": False,
        "places_real_order": False,
        "gate": "blocked_human_only",
        "label": "OPERATOR GATED",
    }


# ── Compact model helpers ─────────────────────────────────────────────────────

def _row_has_quarantine(row: dict[str, Any]) -> bool:
    account_scope = str(row.get("account_scope") or "").upper()
    if account_scope == "QUARANTINED_INVALID_ACCOUNT":
        return True
    if row.get("contains_quarantined_positions") is True:
        return True
    if row.get("quarantine_reasons") not in (None, "", [], {}):
        return True
    reason = str(row.get("reason_if_untrusted") or row.get("quarantine_reason") or "").upper()
    return bool(reason and reason != "NONE")


def _paper_account_truth_fields(
    *,
    source_type: str,
    contains_quarantined_positions: bool = False,
    reason_if_untrusted: str | None = None,
) -> dict[str, Any]:
    trusted = not contains_quarantined_positions and not reason_if_untrusted
    return {
        "account_scope": "PAPER_SIM_ACCOUNT" if trusted else "QUARANTINED_INVALID_ACCOUNT",
        "source_type": source_type,
        "paper_or_live": "paper",
        "contains_simulated_positions": True,
        "contains_live_positions": False,
        "contains_quarantined_positions": contains_quarantined_positions,
        "equity_trusted": trusted,
        "pnl_trusted": trusted,
        "reason_if_untrusted": reason_if_untrusted
        or ("INVALID_OR_QUARANTINED_PAPER_ROWS_PRESENT" if contains_quarantined_positions else None),
        "routes_to_live": False,
    }


def _paper_account_session_fields(
    r: Any | None,
    hb: dict[str, Any],
    *,
    source_type: str,
) -> dict[str, Any]:
    portfolio = (_redis_get_json(r, "v2:portfolio:state") if r else None) or {}
    portfolio_present = bool(portfolio)
    session = (_redis_get_json(r, "v2:paper:session") if r else None) or {}
    canonical = build_canonical_pnl(r) if r else {}

    ledger: dict[str, Any] = {}
    ledger_loaded = False

    def _ledger() -> dict[str, Any]:
        nonlocal ledger, ledger_loaded
        if not ledger_loaded:
            ledger = (_redis_get_json(r, "v2:paper:ledger") if r else None) or {}
            ledger_loaded = True
        return ledger

    def _first_float(*values: Any) -> float | None:
        for value in values:
            parsed = _optional_float(value)
            if parsed is not None:
                return parsed
        return None
    def _first_int_or_none(*values: Any) -> int | None:
        for value in values:
            if value is None or value == "":
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
        return None

    initial_capital = _first_float(
        session.get("starting_equity_usd"),
        session.get("initial_capital"),
        portfolio.get("starting_equity_usd"),
        portfolio.get("initial_capital"),
    )
    if initial_capital is None:
        ledger_payload = _ledger()
        initial_capital = _first_float(
            ledger_payload.get("starting_equity_usd"),
            ledger_payload.get("initial_capital"),
        )
    equity = _first_float(portfolio.get("equity"))
    if equity is None:
        equity = (
            initial_capital
            + (
                _first_float(
                    portfolio.get("realized_net_pnl_usd"),
                    portfolio.get("clean_session_valid_realized_pnl_usd"),
                    portfolio.get("realized_pnl_usd"),
                )
                or 0.0
            )
            + (_first_float(portfolio.get("unrealized_pnl_usd")) or 0.0)
            if initial_capital is not None
            else None
        )
    if portfolio_present:
        realized_pnl = _first_float(
            portfolio.get("realized_net_pnl_usd"),
            portfolio.get("clean_session_valid_realized_pnl_usd"),
            portfolio.get("realized_pnl_usd"),
        )
        unrealized_pnl = _first_float(portfolio.get("unrealized_pnl_usd"))
        total_pnl = _first_float(
            portfolio.get("total_pnl_usd"),
            (realized_pnl + unrealized_pnl)
            if realized_pnl is not None and unrealized_pnl is not None
            else None,
        )
        account_source = "redis:v2:portfolio:state"
    else:
        ledger_payload = _ledger()
        realized_pnl = _first_float(
            ledger_payload.get("realized_pnl_usd"),
            hb.get("realized_pnl_usd"),
        )
        unrealized_pnl = _first_float(
            ledger_payload.get("unrealized_pnl_usd"),
            hb.get("unrealized_pnl_usd"),
        )
        total_pnl = (
            realized_pnl + unrealized_pnl
            if realized_pnl is not None and unrealized_pnl is not None
            else None
        )
        account_source = "fallback:v2:paper:ledger+v2:paper:heartbeat"
    paper_session_id = (
        session.get("paper_session_id")
        or portfolio.get("paper_session_id")
        or session.get("session_id")
        or portfolio.get("session_id")
        or hb.get("paper_session_id")
        or hb.get("session_id")
    )
    if paper_session_id is None:
        ledger_payload = _ledger()
        paper_session_id = ledger_payload.get("paper_session_id") or ledger_payload.get("session_id")
    return {
        "paper_session_id": paper_session_id,
        "equity": equity,
        "paper_equity": equity,
        "paper_equity_usd": canonical.get("paper_equity_usd", equity),
        "paper_balance": equity,
        "available_balance": equity,
        "available_balance_usd": equity,
        "available_balance_scope": "PAPER_SIM_ACCOUNT_NOT_LIVE_SIGNED_ACCOUNT",
        "available_balance_source": "paper_equity_from_v2_portfolio_state_not_live_signed_account",
        "used_balance": _first_float(portfolio.get("open_position_notional"), hb.get("total_open_notional")) or 0.0,
        "initial_capital": initial_capital,
        "starting_equity_usd": initial_capital,
        "paper_initial_capital": initial_capital,
        "realized_pnl": realized_pnl,
        "realized_pnl_usd": realized_pnl,
        "realized_net_pnl_usd": realized_pnl,
        "paper_realized_pnl_usd": canonical.get("paper_realized_pnl_usd", realized_pnl),
        "realized_gross_pnl_usd": _first_float(portfolio.get("realized_gross_pnl_usd")),
        "unrealized_pnl": unrealized_pnl,
        "unrealized_pnl_usd": unrealized_pnl,
        "paper_unrealized_pnl_usd": canonical.get("paper_unrealized_pnl_usd", unrealized_pnl),
        "total_pnl_usd": total_pnl,
        "paper_total_pnl_usd": canonical.get("paper_total_pnl_usd", total_pnl),
        "open_position_count": _first_int_or_none(
            portfolio.get("open_positions_count"),
            None if portfolio_present else _ledger().get("open_position_count"),
            None if portfolio_present else hb.get("open_position_count"),
            None if portfolio_present else hb.get("accepted_position_count"),
        ),
        "closed_trade_count": _first_int_or_none(
            portfolio.get("closed_trade_count"),
            portfolio.get("closed_positions_count"),
            None if portfolio_present else _ledger().get("closed_trade_count"),
            None if portfolio_present else hb.get("closed_trade_count"),
        ),
        "account_source": account_source,
        "data_source": canonical.get("data_source") or account_source,
        "pnl_source_key": portfolio.get("pnl_source_key", "v2:portfolio:state" if portfolio_present else None),
        "pnl_source_route": portfolio.get("pnl_source_route", "/api/v2/portfolio" if portfolio_present else None),
        "pnl_source_type": portfolio.get(
            "pnl_source_type",
            "CANONICAL_CURRENT_SESSION_RUNTIME" if portfolio_present else "FALLBACK_LEGACY_PAPER_RUNTIME",
        ),
        "pnl_conflict_detected": portfolio.get("pnl_conflict_detected", False if portfolio_present else True),
        "pnl_conflict_reason": portfolio.get("pnl_conflict_reason"),
        "pnl_conflict_sources": portfolio.get("pnl_conflict_sources", []),
        "closed_ledger_net_pnl_usd": portfolio.get("closed_ledger_net_pnl_usd"),
        "portfolio_realized_matches_closed_ledger": portfolio.get("portfolio_realized_matches_closed_ledger"),
        "equity_reconciles_within_1_cent": portfolio.get("equity_reconciles_within_1_cent"),
        "source_generated_utc": portfolio.get("generated_utc") or portfolio.get("generated_at"),
        "freshness_seconds": portfolio.get("freshness_seconds"),
        "staleness_seconds": canonical.get("staleness_seconds"),
        "freshness_status": canonical.get("freshness_status"),
        "source_type": source_type,
    }


def _sanitize_decision_reasoning(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return decision_reasoning with all fields as mobile-safe JSON types.

    Redis sometimes stores paper_fill_status as a Python bool (True/False).
    Swift's JSONDecoder is strict: it cannot decode bool where String? is expected,
    so we coerce to string here. All other fields pass through unchanged.
    """
    if not isinstance(raw, dict):
        return None
    out = dict(raw)
    v = out.get("paper_fill_status")
    if v is not None and not isinstance(v, str):
        out["paper_fill_status"] = "accepted" if v is True else "blocked" if v is False else str(v)
    return out


def _compact_position(pos: dict[str, Any]) -> dict[str, Any]:
    contains_quarantined = _row_has_quarantine(pos)
    truth_fields = _paper_account_truth_fields(
        source_type=str(pos.get("source_type") or "paper_mobile_position"),
        contains_quarantined_positions=contains_quarantined,
        reason_if_untrusted=str(pos.get("reason_if_untrusted") or pos.get("quarantine_reason") or "")
        or None,
    )
    entry_price, entry_price_source = _first_positive_price_with_source(
        pos,
        [
            ("entry_price", str(pos.get("entry_price_source") or "entry_price")),
            ("avg_entry_price", "avg_entry_price"),
            ("paper_entry_price", "paper_entry_price"),
            ("entry_fill_price", "entry_fill_price"),
            ("filled_entry_price", "filled_entry_price"),
            ("entry_avg_price", "entry_avg_price"),
            ("avg_fill_price", "avg_fill_price"),
            ("price_at_entry", "price_at_entry"),
            ("open_price", "open_price"),
            ("fill_price", "fill_price"),
        ],
    )
    exit_price, exit_price_source = _first_positive_price_with_source(
        pos,
        [
            ("exit_price", str(pos.get("exit_price_source") or "exit_price")),
            ("paper_exit_price", "paper_exit_price"),
            ("close_price", "close_price"),
            ("closing_price", "closing_price"),
            ("closed_price", "closed_price"),
            ("close_fill_price", "close_fill_price"),
            ("closing_fill_price", "closing_fill_price"),
            ("filled_exit_price", "filled_exit_price"),
            ("exit_fill_price", "exit_fill_price"),
            ("avg_exit_price", "avg_exit_price"),
            ("exit_mark_price", "exit_mark_price"),
        ],
    )
    mark_price, mark_price_source = _first_positive_price_with_source(
        pos,
        [
            ("mark_price", str(pos.get("mark_price_source") or "mark_price")),
            ("last_mark_price", str(pos.get("last_mark_price_source") or "last_mark_price")),
            ("latest_mark_price", str(pos.get("latest_mark_price_source") or "latest_mark_price")),
            ("current_price", str(pos.get("current_price_source") or "current_price")),
        ],
    )
    return {
        "id": str(pos.get("position_id") or pos.get("id") or ""),
        "symbol": str(pos.get("symbol") or ""),
        "side": str(pos.get("side") or ""),
        "qty": _position_quantity(pos),
        "entry_price": entry_price,
        "entry_price_source": entry_price_source or pos.get("entry_price_source"),
        "exit_price": exit_price,
        "exit_price_source": exit_price_source or pos.get("exit_price_source"),
        "mark_price": mark_price,
        "mark_price_source": mark_price_source or pos.get("mark_price_source"),
        "mark_price_generated_at": pos.get("mark_price_generated_at"),
        "mark_price_age_seconds": _optional_float(pos.get("mark_price_age_seconds")),
        "mark_price_stale": bool(pos.get("mark_price_stale")),
        "unrealized_pnl": _optional_float(pos.get("unrealized_pnl")),
        "realized_pnl": _safe_float(_first_present(pos.get("realized_pnl"), pos.get("realized_pnl_usd"))),
        "opened_at": str(pos.get("opened_at") or pos.get("opened_utc") or pos.get("created_at") or ""),
        "closed_at": str(pos.get("closed_at") or pos.get("exit_price_utc") or pos.get("closed_utc") or ""),
        "close_reason": pos.get("close_reason") or pos.get("exit_reason"),
        "status": str(pos.get("status") or "open"),
        "signal_id": pos.get("signal_id"),
        "prediction_id": pos.get("prediction_id"),
        "decision_reasoning": _sanitize_decision_reasoning(pos.get("decision_reasoning") if isinstance(pos.get("decision_reasoning"), dict) else None),
        **truth_fields,
    }


def _mobile_closed_positions(client: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        from app.api.v2.market_contracts import (  # noqa: PLC0415
            _first_positive_price_with_source,
            _latest_position_signal_reasoning,
            _row_position_reasoning,
        )
    except Exception:
        _first_positive_price_with_source = None
        _latest_position_signal_reasoning = None
        _row_position_reasoning = None

    projected: list[dict[str, Any]] = []
    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        if _first_positive_price_with_source is not None:
            entry_price, entry_price_source = _first_positive_price_with_source(
                row,
                [
                    ("entry_price", "entry_price"),
                    ("avg_entry_price", "avg_entry_price"),
                    ("paper_entry_price", "paper_entry_price"),
                    ("entry_fill_price", "entry_fill_price"),
                    ("filled_entry_price", "filled_entry_price"),
                    ("entry_avg_price", "entry_avg_price"),
                    ("avg_fill_price", "avg_fill_price"),
                    ("price_at_entry", "price_at_entry"),
                    ("open_price", "open_price"),
                    ("fill_price", "fill_price"),
                ],
            )
            exit_price, exit_price_source = _first_positive_price_with_source(
                row,
                [
                    ("exit_price", "exit_price"),
                    ("paper_exit_price", "paper_exit_price"),
                    ("close_price", "close_price"),
                    ("closing_price", "closing_price"),
                    ("closed_price", "closed_price"),
                    ("close_fill_price", "close_fill_price"),
                    ("closing_fill_price", "closing_fill_price"),
                    ("filled_exit_price", "filled_exit_price"),
                    ("exit_fill_price", "exit_fill_price"),
                    ("avg_exit_price", "avg_exit_price"),
                    ("exit_mark_price", "exit_mark_price"),
                ],
            )
        else:
            entry_price, entry_price_source = _optional_positive_float(row.get("entry_price")), row.get("entry_price_source")
            exit_price, exit_price_source = _optional_positive_float(row.get("exit_price")), row.get("exit_price_source")

        if _latest_position_signal_reasoning is not None and sym:
            reasoning = _latest_position_signal_reasoning(
                client,
                sym,
                row,
                row_source="v2:paper:closed_trades",
            )
        elif _row_position_reasoning is not None:
            reasoning = _row_position_reasoning(row, source="v2:paper:closed_trades")
        else:
            reasoning = row.get("decision_reasoning") if isinstance(row.get("decision_reasoning"), dict) else None

        projected.append({
            **row,
            "position_id": row.get("position_id") or row.get("close_id") or row.get("id"),
            "symbol": sym or row.get("symbol"),
            "entry_price": entry_price,
            "entry_price_source": entry_price_source,
            "exit_price": exit_price,
            "exit_price_source": exit_price_source,
            "status": "closed",
            "closed_at": row.get("closed_at") or row.get("exit_price_utc") or row.get("closed_utc"),
            "signal_id": row.get("signal_id") or (reasoning or {}).get("signal_id"),
            "prediction_id": row.get("prediction_id") or (reasoning or {}).get("prediction_id"),
            "decision_reasoning": reasoning,
        })

    projected.sort(key=lambda item: str(item.get("closed_at") or item.get("exit_price_utc") or ""), reverse=True)
    return [_compact_position(row) for row in projected]


def _mobile_enriched_open_positions(client: Any, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    default_metrics = {
        "unrealized_pnl_usd": 0.0,
        "total_open_notional": 0.0,
        "mark_to_market_live": False,
        "live_mark_price_count": 0,
        "stale_mark_price_count": 0,
        "missing_mark_price_count": len(rows),
    }
    if client is None:
        return [_compact_position(row) for row in rows], default_metrics

    try:
        from app.api.v2.market_contracts import _enrich_paper_positions  # noqa: PLC0415
    except Exception:
        return [_compact_position(row) for row in rows], default_metrics

    risk_profile = _redis_get_json(client, "v2:risk:active_profile") or {}
    risk_fields = risk_profile.get("fields") if isinstance(risk_profile.get("fields"), dict) else {}
    max_leverage = _safe_float(risk_fields.get("max_leverage"), 1.0)
    if max_leverage <= 0:
        max_leverage = 1.0

    try:
        enriched, metrics = _enrich_paper_positions(client, rows, max_leverage=max_leverage)
    except Exception:
        return [_compact_position(row) for row in rows], default_metrics

    return [_compact_position(row) for row in enriched], {**default_metrics, **metrics}


def _compact_signal(sig: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(sig.get("signal_id") or sig.get("id") or ""),
        "symbol": str(sig.get("symbol") or ""),
        "timeframe": str(sig.get("timeframe") or ""),
        "action": str(sig.get("action") or ""),
        "confidence": _safe_float(sig.get("confidence")),
        "confidence_selected_action": _safe_float(sig.get("confidence_selected_action")),
        "confidence_executable_trade": _safe_float(sig.get("confidence_executable_trade")),
        "confidence_display_label": sig.get("confidence_display_label"),
        "confidence_type": sig.get("confidence_type"),
        "confidence_a_plus_eligible": sig.get("confidence_a_plus_eligible") is True,
        "confidence_tradeability_block_reasons": _as_list(sig.get("confidence_tradeability_block_reasons")),
        "paper_exploration_tier": sig.get("paper_exploration_tier") or sig.get("exploration_tier"),
        "exploration_tier": sig.get("exploration_tier") or sig.get("paper_exploration_tier"),
        "expected_net_pnl_usd": _safe_float(sig.get("expected_net_pnl_usd")),
        "expected_max_loss_usd": _safe_float(sig.get("expected_max_loss_usd") or sig.get("max_loss_usd")),
        "why_not_a_plus": _as_list(sig.get("block_reasons")),
        "why_not_live_ready": _as_list(sig.get("live_ready_block_reasons") or sig.get("block_reasons")),
        "risk_controller_decision": sig.get("risk_decision") or sig.get("risk_state"),
        "allocator_decision": sig.get("allocator_decision"),
        "trainer_feedback_status": sig.get("trainer_feedback_status"),
        "actionable": bool(sig.get("paper_fill_allowed")),
        "risk_state": str(sig.get("risk_state") or ""),
        "paper_fill_status": str(sig.get("paper_fill_status") or ""),
        "published_at": str(sig.get("available_at") or sig.get("decision_time") or ""),
        "last_price": _safe_float(sig.get("last_price")),
        "expected_move_bps": _safe_float(sig.get("expected_move_bps")),
        "data_coverage": _safe_float(sig.get("data_coverage_percent")),
        # Model provenance (the raw signal payload carries both; without these
        # the iOS prediction detail rows can never render them).
        "model_version": sig.get("model_version"),
        "checkpoint_id": sig.get("checkpoint_id"),
    }


def _compact_alert(alert: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(alert.get("alert_id") or alert.get("id") or ""),
        "symbol": str(alert.get("symbol") or ""),
        "type": str(alert.get("alert_type") or alert.get("type") or ""),
        "message": str(alert.get("message") or alert.get("summary") or ""),
        "severity": str(alert.get("severity") or "info"),
        "triggered_at": str(alert.get("triggered_at") or alert.get("created_at") or ""),
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/dashboard")
async def get_mobile_dashboard(
    actor: UserRecord | None = Depends(optional_auth),
) -> dict[str, Any]:
    """Compact system overview for mobile home screen."""
    try:
        r = get_redis()
    except Exception:
        r = None

    hb = _paper_heartbeat(r) if r else {}
    trainer = _trainer_status_from_redis(r) if r else {}
    gpu = _gpu_status_from_redis(r) if r else {}
    live_gate = _live_gate_status()
    account_fields = _paper_account_session_fields(
        r,
        hb,
        source_type="paper_mobile_dashboard",
    )

    open_count = _safe_int(
        account_fields.get("open_position_count")
        if account_fields.get("open_position_count") is not None
        else hb.get("open_position_count") or hb.get("accepted_position_count")
    )
    closed_count = _safe_int(
        account_fields.get("closed_trade_count")
        if account_fields.get("closed_trade_count") is not None
        else hb.get("closed_trade_count")
    )
    realized_pnl = _safe_float(account_fields.get("realized_pnl_usd"))
    unrealized_pnl = _safe_float(account_fields.get("unrealized_pnl_usd"))

    alerts_preview: list[dict[str, Any]] = []
    if r:
        raw_alerts = _alerts_from_redis(r, limit=5)
        alerts_preview = [_compact_alert(a) for a in raw_alerts]

    # Signal count from live keys
    signal_count = 0
    signal_count_capped = False
    if r:
        try:
            signal_count = len(_signal_latest_keys(r))
        except Exception:
            signal_count = 0

    return {
        "schema_version": "mobile_dashboard_v2",
        "generated_utc": _utc_now(),
        "generated_at_utc": _utc_now(),
        "generated_at_et": _et_now(),
        "source": "mobile_compact_runtime_contract",
        "staleness_seconds": account_fields.get("staleness_seconds"),
        "freshness_status": account_fields.get("freshness_status"),
        "canonical_owner": "/api/v2/mobile/dashboard",
        "routes_to_live": False,
        "places_real_order": False,
        "data_quality_status": "partial" if account_fields.get("freshness_status") in {"stale", "unavailable"} else "fresh",
        "live_gate": live_gate,
        "paper": {
            **account_fields,
            **_mobile_a_plus_runtime_summary(r),
            **_mobile_paper_charts(r),
            "open_positions": open_count,
            "closed_trades": closed_count,
            "realized_pnl_usd": realized_pnl,
            "unrealized_pnl_usd": unrealized_pnl,
            "signals_seen": _safe_int(hb.get("paper_signals_seen")),
            "intents_accepted": _safe_int(hb.get("intents_accepted")),
            "intents_blocked": _safe_int(hb.get("intents_blocked")),
            "classification": str(hb.get("classification") or "UNKNOWN"),
            "places_real_order": False,
        },
        "trainer": {
            "state": trainer.get("state", "UNKNOWN"),
            "checkpoint": trainer.get("checkpoint", ""),
            "model_source": trainer.get("model_source", ""),
            "champion_challenger_status": trainer.get("champion_challenger_status"),
            "cuda_active": bool(trainer.get("cuda_active")),
            "device": str(trainer.get("device") or ""),
            "gpu_name": str(trainer.get("gpu_name") or ""),
            "data_coverage": _safe_float(trainer.get("data_coverage")),
            "training_steps_total": _safe_int(trainer.get("training_steps_total")),
            "training_steps_last_hour": _safe_int(trainer.get("training_steps_last_hour")),
            "model_id": str(trainer.get("model_id") or ""),
            "input_dim": trainer.get("input_dim"),
            "feature_count": trainer.get("feature_count"),
            "temporal_encoder": str(trainer.get("temporal_encoder") or ""),
            "temporal_encoder_enabled": bool(trainer.get("temporal_encoder_enabled")),
            "effective_trainer_mode": str(trainer.get("effective_trainer_mode") or ""),
            "online_learning_status": str(trainer.get("online_learning_status") or ""),
            "weights_updating": bool(trainer.get("weights_updating")),
            "trainer_process_status": str(trainer.get("trainer_process_status") or ""),
            "backtest_win_rate": _safe_float(trainer.get("backtest_win_rate")) if trainer.get("backtest_win_rate") is not None else None,
            "backtest_expectancy_bps": _safe_float(trainer.get("backtest_expectancy_bps")) if trainer.get("backtest_expectancy_bps") is not None else None,
            "backtest_profit_factor": _safe_float(trainer.get("backtest_profit_factor")) if trainer.get("backtest_profit_factor") is not None else None,
            "throughput_predictions_per_second": _safe_float(trainer.get("throughput_predictions_per_second")) if trainer.get("throughput_predictions_per_second") is not None else None,
            "vram_used_mb": _safe_float(trainer.get("vram_used_mb")) if trainer.get("vram_used_mb") is not None else None,
            "generalization_gap": _safe_float(trainer.get("generalization_gap")) if trainer.get("generalization_gap") is not None else None,
            "validation_loss_delta": _safe_float(trainer.get("validation_loss_delta")) if trainer.get("validation_loss_delta") is not None else None,
        },
        "gpu": {
            "name": str(gpu.get("name") or ""),
            "device": str(gpu.get("device") or ""),
            "utilization_pct": _safe_float(gpu.get("utilization_pct")),
            "vram_used_mb": _safe_int(gpu.get("vram_used_mb")),
            "vram_total_mb": _safe_int(gpu.get("vram_total_mb")),
        },
        "alerts_preview": alerts_preview,
        "redis_connected": r is not None,
        "active_signal_count": signal_count,
        "active_signal_count_capped": signal_count_capped,
    }


@router.get("/positions")
async def get_mobile_positions(
    actor: UserRecord | None = Depends(optional_auth),
) -> dict[str, Any]:
    """Compact paper positions list for mobile positions tab."""
    try:
        r = get_redis()
    except Exception:
        r = None

    raw_positions = _paper_positions_from_redis(r) if r else []
    raw_closed_trades = _paper_closed_trades_from_redis(r) if r else []
    hb = _paper_heartbeat(r) if r else {}

    position_pricing: dict[str, Any] | None = None
    position_warnings: list[str] = []
    projected_positions = raw_positions
    if r:
        try:
            from app.api.v2.market_contracts import (  # noqa: PLC0415
                _enrich_paper_positions,
                _paper_positions_with_last_known_fallback,
                _redis_risk_max_leverage,
            )

            projected_positions, _source_status, position_warnings = _paper_positions_with_last_known_fallback(raw_positions)
            projected_positions, position_pricing = _enrich_paper_positions(
                r,
                projected_positions,
                max_leverage=_redis_risk_max_leverage(r),
            )
        except Exception as exc:
            position_warnings = [f"Position mark projection unavailable: {exc}"]

    positions = [_compact_position(p) for p in projected_positions]
    closed_positions = _mobile_closed_positions(r, _recent_closed_trade_rows(raw_closed_trades, 200)) if r else []
    contains_quarantined = any(
        p.get("contains_quarantined_positions") is True
        for p in [*positions, *closed_positions]
    )
    truth_fields = _paper_account_truth_fields(
        source_type="paper_mobile_positions",
        contains_quarantined_positions=contains_quarantined,
    )
    account_fields = _paper_account_session_fields(
        r,
        hb,
        source_type="paper_mobile_positions",
    )
    realized_pnl = _safe_float(account_fields.get("realized_pnl_usd"))
    account_unrealized = _safe_float(account_fields.get("unrealized_pnl_usd"))
    enriched_unrealized = (
        _optional_float(position_pricing.get("unrealized_pnl_usd"))
        if isinstance(position_pricing, dict)
        else None
    )
    unrealized_pnl = account_unrealized if account_unrealized is not None else _safe_float(enriched_unrealized)
    total_pnl = _safe_float(account_fields.get("total_pnl_usd"), realized_pnl + unrealized_pnl)

    return {
        "generated_utc": _utc_now(),
        "positions": positions,
        "closed_positions": closed_positions[:50],
        "historical_positions": closed_positions[:200],
        "position_pricing": position_pricing,
        "warnings": position_warnings,
        "summary": {
            "open_count": len(positions),
            "closed_count": _safe_int(hb.get("closed_trade_count") or len(closed_positions)),
            "total_pnl_usd": total_pnl,
            "realized_pnl_usd": realized_pnl,
            "realized_net_pnl_usd": realized_pnl,
            "unrealized_pnl_usd": unrealized_pnl,
            "pnl_source_key": account_fields.get("pnl_source_key"),
            "pnl_source_route": account_fields.get("pnl_source_route"),
            "pnl_source_type": account_fields.get("pnl_source_type"),
            "pnl_conflict_detected": account_fields.get("pnl_conflict_detected"),
            **truth_fields,
        },
        "mode": "paper",
        "live_gate": "blocked_human_only",
        "places_real_order": False,
        **account_fields,
        **truth_fields,
    }


@router.get("/signals")
async def get_mobile_signals(
    limit: int = 150,
    actionable_only: bool = False,
    actor: UserRecord | None = Depends(optional_auth),
) -> dict[str, Any]:
    """Compact signals feed from v2:signals:latest:* per-symbol keys. Max 200."""
    limit = min(max(1, limit), 200)
    try:
        r = get_redis()
    except Exception:
        r = None

    raw = _signal_matrix_from_redis(r, limit=limit * 2) if r else []

    if actionable_only:
        raw = [s for s in raw if s.get("paper_fill_allowed")]

    signals = [_compact_signal(s) for s in raw[:limit]]

    return {
        "generated_utc": _utc_now(),
        "signals": signals,
        "total_returned": len(signals),
        "actionable_only": actionable_only,
    }


@router.get("/alerts")
async def get_mobile_alerts(
    limit: int = 30,
    actor: UserRecord | None = Depends(optional_auth),
) -> dict[str, Any]:
    """Recent market alerts for mobile alerts tab."""
    limit = min(max(1, limit), 100)
    try:
        r = get_redis()
    except Exception:
        r = None

    raw = _alerts_from_redis(r, limit=limit) if r else []
    alerts = [_compact_alert(a) for a in raw]

    return {
        "generated_utc": _utc_now(),
        "alerts": alerts,
        "total_returned": len(alerts),
    }


@router.get("/health")
async def get_mobile_health(
    actor: UserRecord | None = Depends(optional_auth),
) -> dict[str, Any]:
    """System health check for mobile status bar and watch face."""
    try:
        r = get_redis()
        redis_ok = True
    except Exception:
        r = None
        redis_ok = False

    trainer = _trainer_status_from_redis(r) if r else {}
    gpu = _gpu_status_from_redis(r) if r else {}
    hb = _paper_heartbeat(r) if r else {}
    account_fields = _paper_account_session_fields(
        r,
        hb,
        source_type="paper_mobile_health",
    )

    trainer_state = str(trainer.get("state") or "UNKNOWN")
    cuda_active = bool(trainer.get("cuda_active"))
    training_active = cuda_active or "ACTIVE" in trainer_state.upper()
    paper_classification = str(hb.get("classification") or "UNKNOWN")

    overall = "healthy" if (redis_ok and training_active) else "degraded" if redis_ok else "unavailable"

    return {
        "generated_utc": _utc_now(),
        "overall": overall,
        "redis_connected": redis_ok,
        "trainer": {
            "state": trainer_state,
            "cuda_active": cuda_active,
            "training_active": training_active,
            "checkpoint": str(trainer.get("checkpoint") or ""),
            "champion_challenger_status": trainer.get("champion_challenger_status"),
            "device": str(trainer.get("device") or ""),
            "gpu_name": str(trainer.get("gpu_name") or ""),
            "model_id": str(trainer.get("model_id") or ""),
            "input_dim": trainer.get("input_dim"),
            "feature_count": trainer.get("feature_count"),
            "temporal_encoder": str(trainer.get("temporal_encoder") or ""),
            "temporal_encoder_enabled": bool(trainer.get("temporal_encoder_enabled")),
            "effective_trainer_mode": str(trainer.get("effective_trainer_mode") or ""),
            "online_learning_status": str(trainer.get("online_learning_status") or ""),
            "weights_updating": bool(trainer.get("weights_updating")),
            "trainer_process_status": str(trainer.get("trainer_process_status") or ""),
            "backtest_win_rate": _safe_float(trainer.get("backtest_win_rate")) if trainer.get("backtest_win_rate") is not None else None,
            "backtest_expectancy_bps": _safe_float(trainer.get("backtest_expectancy_bps")) if trainer.get("backtest_expectancy_bps") is not None else None,
            "backtest_profit_factor": _safe_float(trainer.get("backtest_profit_factor")) if trainer.get("backtest_profit_factor") is not None else None,
            "throughput_predictions_per_second": _safe_float(trainer.get("throughput_predictions_per_second")) if trainer.get("throughput_predictions_per_second") is not None else None,
            "vram_used_mb": _safe_float(trainer.get("vram_used_mb")) if trainer.get("vram_used_mb") is not None else None,
            "generalization_gap": _safe_float(trainer.get("generalization_gap")) if trainer.get("generalization_gap") is not None else None,
            "validation_loss_delta": _safe_float(trainer.get("validation_loss_delta")) if trainer.get("validation_loss_delta") is not None else None,
        },
        "gpu": {
            "name": str(gpu.get("name") or ""),
            "device": str(gpu.get("device") or ""),
            "utilization_pct": _safe_float(gpu.get("utilization_pct")),
            "vram_used_mb": _safe_int(gpu.get("vram_used_mb")),
            "vram_total_mb": _safe_int(gpu.get("vram_total_mb")),
            "temperature_c": _safe_float(gpu.get("temperature_c")),
        },
        "paper": {
            **account_fields,
            **_mobile_a_plus_runtime_truth(r),
            "classification": paper_classification,
            "open_positions": _safe_int(
                account_fields.get("open_position_count")
                if account_fields.get("open_position_count") is not None
                else hb.get("open_position_count")
            ),
            "intents_accepted": _safe_int(hb.get("intents_accepted")),
            "intents_blocked": _safe_int(hb.get("intents_blocked")),
        },
        "ingestors": _ingestors_payload(r),
        "live_gate": "blocked_human_only",
        "places_real_order": False,
    }


@router.get("/risk-status")
async def get_mobile_risk_status(
    actor: UserRecord | None = Depends(optional_auth),
) -> dict[str, Any]:
    """Risk gate status for mobile risk control tab."""
    try:
        r = get_redis()
    except Exception:
        r = None

    risk = _risk_status_from_redis(r) if r else {}
    hb = _paper_heartbeat(r) if r else {}
    compact_truth = _mobile_a_plus_runtime_summary(r)
    preemptive_truth = _mobile_preemptive_edge_control_truth(r)

    return {
        "schema_version": "mobile_risk_status_v2",
        "generated_utc": _utc_now(),
        "generated_at_utc": _utc_now(),
        "generated_at_et": _et_now(),
        "source": "mobile_compact_runtime_contract",
        "staleness_seconds": None,
        "freshness_status": "fresh" if r is not None else "unavailable",
        "canonical_owner": "/api/v2/mobile/risk-status",
        "routes_to_live": False,
        "places_real_order": False,
        "data_quality_status": "fresh" if r is not None else "unavailable",
        "live_gate": _live_gate_status(),
        "risk_state": str(risk.get("state") or "UNKNOWN"),
        "risk_classification": str(risk.get("classification") or ""),
        "paper_blocked_count": _safe_int(hb.get("intents_blocked")),
        "paper_accepted_count": _safe_int(hb.get("intents_accepted")),
        "kill_switch_active": bool(risk.get("kill_switch_active", True)),
        "fail_closed": bool(risk.get("fail_closed", True)),
        "decisions_processed_total": _safe_int(risk.get("decisions_processed_total")),
        "max_position_size_usd": _safe_float(risk.get("max_position_size_usd")),
        "daily_loss_limit_usd": _safe_float(risk.get("daily_loss_limit_usd")),
        "current_daily_loss_usd": _safe_float(risk.get("current_daily_loss_usd")),
        "dangerous_actions_require_human_approval": True,
        "mobile_can_approve_dangerous_actions": False,
        "hedge": _hedge_payload(r),
        **compact_truth,
        **preemptive_truth,
    }


@router.get("/paper-summary")
async def get_mobile_paper_summary(
    actor: UserRecord | None = Depends(optional_auth),
) -> dict[str, Any]:
    """Paper trading summary for mobile paper trading tab."""
    try:
        r = get_redis()
    except Exception:
        r = None

    hb = _paper_heartbeat(r) if r else {}
    positions = _paper_positions_from_redis(r) if r else []
    positions_enriched, position_pricing = _mobile_enriched_open_positions(r, positions)

    signals_seen = _safe_int(hb.get("paper_signals_seen"))
    intents_built = _safe_int(hb.get("intents_built"))
    intents_accepted = _safe_int(hb.get("intents_accepted"))
    intents_blocked = _safe_int(hb.get("intents_blocked"))
    open_count = _safe_int(hb.get("open_position_count") or hb.get("accepted_position_count") or len(positions_enriched))
    closed_count = _safe_int(hb.get("closed_trade_count"))
    realized_pnl = _safe_float(hb.get("realized_pnl_usd"))
    enriched_unrealized = _optional_float(position_pricing.get("unrealized_pnl_usd"))
    unrealized_pnl = enriched_unrealized if positions_enriched and enriched_unrealized is not None else _safe_float(hb.get("unrealized_pnl_usd"))
    outcome_labels = _safe_int(hb.get("outcome_label_count"))
    feedback_consumable = _safe_int(hb.get("trainer_feedback_consumable_row_count"))
    feedback_quarantined = _safe_int(hb.get("trainer_feedback_quarantined_row_count"))
    runtime_truth = _mobile_runtime_truth_from_redis(r, hb)
    contains_quarantined = any(_row_has_quarantine(position) for position in positions_enriched)
    truth_fields = _paper_account_truth_fields(
        source_type="paper_mobile_summary",
        contains_quarantined_positions=contains_quarantined,
    )
    account_fields = _paper_account_session_fields(
        r,
        hb,
        source_type="paper_mobile_summary",
    )
    open_count = _safe_int(
        account_fields.get("open_position_count")
        if account_fields.get("open_position_count") is not None
        else hb.get("open_position_count") or hb.get("accepted_position_count") or len(positions_enriched)
    )
    closed_count = _safe_int(
        account_fields.get("closed_trade_count")
        if account_fields.get("closed_trade_count") is not None
        else hb.get("closed_trade_count")
    )
    realized_pnl = _safe_float(account_fields.get("realized_pnl_usd"))
    if not positions_enriched:
        unrealized_pnl = _safe_float(account_fields.get("unrealized_pnl_usd"))

    win_rate: float | None = None
    if closed_count > 0:
        win_count = _safe_int(hb.get("winning_trades"))
        if win_count > 0:
            win_rate = round(win_count / closed_count * 100, 1)

    return {
        "generated_utc": _utc_now(),
        "mode": "paper",
        "places_real_order": False,
        "live_gate": "blocked_human_only",
        **truth_fields,
        **account_fields,
        "loop": {
            "signals_seen": signals_seen,
            "intents_built": intents_built,
            "intents_accepted": intents_accepted,
            "intents_blocked": intents_blocked,
            "classification": str(hb.get("classification") or "UNKNOWN"),
            "cycle_state": str(hb.get("cycle_state") or "UNKNOWN"),
            "heartbeat_ttl_seconds": _safe_int(hb.get("heartbeat_ttl_seconds")),
            "candidate_id": str(hb.get("candidate_id") or ""),
            "policy_id": str(hb.get("policy_id") or ""),
            "paper_policy_owner": str(hb.get("paper_policy_owner") or ""),
            "policy_fingerprint": str(hb.get("policy_fingerprint") or ""),
            "model_source": str(hb.get("model_source") or ""),
            "paper_only": bool(hb.get("paper_only", True)),
            "routes_to_live": bool(hb.get("routes_to_live", False)),
            "places_real_order": bool(hb.get("places_real_order", False)),
            **runtime_truth,
        },
        "positions": {
            "open_count": open_count,
            "closed_count": closed_count,
            "positions_preview": positions_enriched[:5],
            **truth_fields,
        },
        "position_pricing": {
            "unrealized_pnl_usd": position_pricing.get("unrealized_pnl_usd"),
            "total_open_notional": position_pricing.get("total_open_notional"),
            "mark_to_market_live": position_pricing.get("mark_to_market_live"),
            "live_mark_price_count": position_pricing.get("live_mark_price_count"),
            "stale_mark_price_count": position_pricing.get("stale_mark_price_count"),
            "missing_mark_price_count": position_pricing.get("missing_mark_price_count"),
        },
        "pnl": {
            "realized_usd": realized_pnl,
            "unrealized_usd": unrealized_pnl,
            "total_usd": _safe_float(
                account_fields.get("total_pnl_usd"),
                realized_pnl + unrealized_pnl,
            ),
            "win_rate_pct": win_rate,
            "equity_trusted": truth_fields["equity_trusted"],
            "pnl_trusted": truth_fields["pnl_trusted"],
            "reason_if_untrusted": truth_fields["reason_if_untrusted"],
            "pnl_source_key": account_fields.get("pnl_source_key"),
            "pnl_source_route": account_fields.get("pnl_source_route"),
            "pnl_source_type": account_fields.get("pnl_source_type"),
            "pnl_conflict_detected": account_fields.get("pnl_conflict_detected"),
        },
        "trainer_feedback": {
            "outcome_labels": outcome_labels,
            "consumable_rows": feedback_consumable,
            "quarantined_rows": feedback_quarantined,
        },
        **_mobile_a_plus_runtime_truth(r),
    }


def _mobile_a_plus_runtime_truth(r: Any) -> dict[str, Any]:
    """A+ goal Phase 12: session performance, freeze, A+ gate, trainer learning
    and real-trader readiness truth for every operator surface."""

    def _coinapi_provider_unusable_status(source: Any) -> str | None:
        if "coinapi" not in str(source or "").lower():
            return None
        try:
            keys = list(r.keys("v2:market:coinapi:rest:status:*") or [])[:20]
        except Exception:
            keys = []
        if not keys:
            return "COINAPI_STATUS_KEYS_MISSING_NOT_CURRENT_SOURCE"

        sampled = 0
        upstream_errors = 0
        usable_payloads = 0
        for key in keys:
            try:
                raw = r.get(key)
                payload = json.loads(raw) if raw else {}
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            sampled += 1
            http_status_raw = payload.get("http_status")
            try:
                http_status = int(http_status_raw)
            except (TypeError, ValueError):
                http_status = None
            has_upstream_error = (
                (http_status is not None and http_status >= 400)
                or bool(payload.get("error"))
                or bool(payload.get("upstream_error"))
                or bool(payload.get("provider_unusable_reason"))
            )
            has_usable_market_data = bool(
                payload.get("orderbook_present")
                or payload.get("ohlcv_present_timeframes")
                or payload.get("ohlcv")
            )
            if has_upstream_error:
                upstream_errors += 1
            elif has_usable_market_data:
                usable_payloads += 1

        if sampled and upstream_errors >= max(1, sampled // 2):
            return "COINAPI_HTTP_FORBIDDEN_OR_EXPIRED_NOT_CURRENT_SOURCE"
        if sampled and usable_payloads == 0:
            return "COINAPI_NO_USABLE_OHLCV_OR_ORDERBOOK_NOT_CURRENT_SOURCE"
        if not sampled:
            return "COINAPI_STATUS_PAYLOADS_UNREADABLE_NOT_CURRENT_SOURCE"
        return None

    governor = _redis_get_json(r, "v2:paper:performance_governor_status") or {}
    halt = _redis_get_json(r, "v2:paper:new_entry_emergency_halt_status") or {}
    freeze = _redis_get_json(r, "v2:paper:entry_freeze") or {}
    a_plus = _redis_get_json(r, "v2:paper:a_plus_gate:status") or {}
    trainer = _redis_get_json(r, "v2:trainer:hybrid_cuda:status") or {}
    rejected = a_plus.get("rejected_reason_matrix")
    top_blockers = list((freeze.get("future_gate_blockers") or []))
    for reason in (halt.get("halt_reasons") or []):
        if reason not in top_blockers:
            top_blockers.append(reason)

    reduced_semantics = _operator_runtime_json(
        "v2_paper_trade_management/latest/a_plus_gate_after_trust_semantics_status.json"
    ) or {}
    reduced_hash_chain = _operator_runtime_json(
        "v2_paper_trade_management/latest/a_plus_reduced_size_bootstrap_hash_chain.json"
    ) or {}
    reduced_generated_at = (
        reduced_semantics.get("generated_at")
        or reduced_semantics.get("generated_utc")
        or reduced_hash_chain.get("generated_at")
        or reduced_hash_chain.get("generated_utc")
    )

    market_hb = _redis_get_json(r, "v2:market:coinapi:ohlcv:heartbeat") or {}
    market_generated_at = (
        market_hb.get("finished_utc")
        or market_hb.get("generated_at")
        or market_hb.get("generated_utc")
        or market_hb.get("ts")
    )
    market_age_seconds: int | None = None
    if isinstance(market_generated_at, str) and market_generated_at:
        try:
            parsed = datetime.fromisoformat(market_generated_at.replace("Z", "+00:00"))
            market_age_seconds = max(
                0,
                int((datetime.now(UTC) - parsed.astimezone(UTC)).total_seconds()),
            )
        except ValueError:
            market_age_seconds = None
    market_freshness_state = (
        "MARKET_FEED_CURRENT"
        if market_age_seconds is not None and market_age_seconds < 600
        else "MARKET_FEED_STALE"
    )
    market_source = market_hb.get("source") or "v2:market:coinapi:ohlcv:heartbeat"
    if market_freshness_state != "MARKET_FEED_CURRENT" and "coinapi" in str(market_source).lower():
        market_source = "coinapi_stale_or_unavailable_not_current_source"
    coinapi_unusable_reason = _coinapi_provider_unusable_status(market_source)
    if coinapi_unusable_reason:
        market_source = "coinapi_provider_unusable_not_current_source"
        market_freshness_state = "MARKET_FEED_PROVIDER_UNUSABLE_NOT_CURRENT"

    closed_count = _safe_int(governor.get("closed_outcome_count")) or 0
    realized_pnl_usd = _safe_float(governor.get("realized_pnl_usd"))
    real_trader_readiness = _mobile_real_trader_readiness(r)
    readiness_blockers = real_trader_readiness.get("readiness_blockers")
    if not isinstance(readiness_blockers, list):
        readiness_blockers = []
    top_blockers = _dedupe_strings([*readiness_blockers, *top_blockers])
    return {
        "performance": {
            "profit_factor": governor.get("profit_factor"),
            "expectancy_usd": (
                round(realized_pnl_usd / max(1, closed_count), 8)
                if realized_pnl_usd is not None and closed_count
                else None
            ),
            "realized_pnl_usd": realized_pnl_usd,
            "notional_weighted_expectancy_bps": governor.get("notional_weighted_expectancy_bps"),
            "win_rate": governor.get("win_rate"),
            "closed_outcome_count": governor.get("closed_outcome_count"),
            "governor_state": governor.get("state"),
        },
        "entry_freeze": {
            "new_entries_allowed": halt.get("new_entries_allowed"),
            "halt_reasons": halt.get("halt_reasons"),
            "future_gate_blockers": freeze.get("future_gate_blockers"),
            "allow_close": halt.get("allow_close"),
            "allow_reduce": halt.get("allow_reduce"),
        },
        "a_plus_gate": {
            "evaluated_candidates": a_plus.get("evaluated_candidates"),
            "a_plus_candidates": a_plus.get("a_plus_candidates"),
            "rejected_reason_matrix": dict(list(rejected.items())[:8]) if isinstance(rejected, dict) else None,
            "gate_is_hard_entry_condition": a_plus.get("gate_is_hard_entry_condition"),
        },
        "reduced_size_bootstrap": {
            "schema_version": "mobile_reduced_size_bootstrap_truth_v1",
            "source": (
                "operator_runtime/v2_paper_trade_management/latest/"
                "a_plus_gate_after_trust_semantics_status.json + "
                "a_plus_reduced_size_bootstrap_hash_chain.json"
            ),
            "generated_at": reduced_generated_at,
            "final_a_plus_candidates": reduced_semantics.get("final_a_plus_candidates"),
            "reduced_size_bootstrap_candidates": reduced_semantics.get(
                "reduced_size_bootstrap_candidates"
            ),
            "closed_rows": reduced_hash_chain.get("closed_rows"),
            "counts_as_final_a_plus": (
                reduced_semantics.get("reduced_size_counts_as_final_a_plus") is True
                or reduced_hash_chain.get("counts_as_final_a_plus") is True
            ),
            "b_grade_counts_as_final_a_plus": (
                reduced_semantics.get("b_grade_counts_as_final_a_plus") is True
            ),
            "routes_to_live": reduced_hash_chain.get("routes_to_live") is True,
            "paper_only": reduced_hash_chain.get("paper_only") is not False,
        },
        "trainer_learning": {
            "effective_trainer_mode": trainer.get("effective_trainer_mode"),
            "online_learning_status": trainer.get("online_learning_status"),
            "last_successful_weight_update_at": trainer.get("last_successful_weight_update_at"),
            "checkpoint_id": trainer.get("checkpoint_id"),
        },
        "real_trader_readiness": {
            **real_trader_readiness,
            "one_flip_packet": "goal_state/V2_FABLE5_FULL_SYSTEM_A_PLUS_LIVE_READY_1000X_MACHINE_COMPLETION/real_trader_one_flip_readiness_packet.json",
        },
        "market_data_freshness": {
            "source": market_source,
            "generated_at": market_generated_at,
            "age_seconds": market_age_seconds,
            "freshness_state": market_freshness_state,
            "provider_current": coinapi_unusable_reason is None,
            "provider_unusable_reason": coinapi_unusable_reason,
        },
        **_mobile_preemptive_edge_control_truth(r),
        "top_blockers": top_blockers[:6],
    }


@router.get("/summary")
async def get_mobile_summary(
    actor: UserRecord | None = Depends(optional_auth),
) -> dict[str, Any]:
    return await get_mobile_paper_summary(actor)


# ── Push notification registration ───────────────────────────────────────────

class PushRegistrationRequest(BaseModel):
    device_token: str
    platform: str = "apns"
    environment: str = "production"
    app_version: str = ""


_PUSH_STORE_KEY = "v2:mobile:push_tokens"


@router.post("/push/register", status_code=status.HTTP_201_CREATED)
async def register_push_token(
    request: PushRegistrationRequest,
    actor: UserRecord = Depends(require_auth),
) -> dict[str, Any]:
    """Register an APNS/FCM device token for push notifications."""
    if not request.device_token or len(request.device_token) < 8:
        raise HTTPException(status_code=400, detail="invalid_device_token")
    if request.platform not in {"apns", "fcm"}:
        raise HTTPException(status_code=400, detail="unsupported_platform")

    try:
        r = get_redis()
        entry = json.dumps({
            "user_id": str(actor.get("user_id", "") if actor else ""),
            "device_token": request.device_token,
            "platform": request.platform,
            "environment": request.environment,
            "app_version": request.app_version,
            "registered_at": _utc_now(),
        })
        r.hset(_PUSH_STORE_KEY, request.device_token, entry)
    except Exception:
        pass

    return {
        "status": "registered",
        "device_token": request.device_token[:8] + "...",
        "platform": request.platform,
        "registered_at": _utc_now(),
        "note": "Push notifications are best-effort.",
    }


@router.delete("/push/{device_token}", status_code=status.HTTP_200_OK)
async def unregister_push_token(
    device_token: str,
    actor: UserRecord = Depends(require_auth),
) -> dict[str, Any]:
    """Unregister an APNS/FCM device token."""
    try:
        r = get_redis()
        r.hdel(_PUSH_STORE_KEY, device_token)
    except Exception:
        pass
    return {"status": "unregistered", "registered_at": _utc_now()}


# ── Admin-only endpoints ──────────────────────────────────────────────────────

@router.get("/admin/summary", tags=["v2-mobile-admin"])
async def get_mobile_admin_summary(
    actor: UserRecord = Depends(require_auth),
) -> dict[str, Any]:
    """Admin overview for mobile admin dashboard. Requires admin role."""
    role_val = str(actor.get("role", "viewer") if actor else "viewer")
    if role_val not in {"admin", "superadmin"}:
        raise HTTPException(status_code=403, detail="admin_required")

    try:
        r = get_redis()
    except Exception:
        r = None

    trainer = _trainer_status_from_redis(r) if r else {}
    gpu = _gpu_status_from_redis(r) if r else {}
    hb = _paper_heartbeat(r) if r else {}
    risk = _risk_status_from_redis(r) if r else {}

    return {
        "generated_utc": _utc_now(),
        "actor": {
            "user_id": str(actor.get("user_id", "") if actor else ""),
            "email": str(actor.get("email", "") if actor else ""),
            "role": role_val,
        },
        "live_gate": _live_gate_status(),
        "trainer": {
            "state": trainer.get("state", "UNKNOWN"),
            "checkpoint": trainer.get("checkpoint", ""),
            "champion_challenger_status": trainer.get("champion_challenger_status"),
            "device": str(trainer.get("device") or ""),
            "gpu_name": str(trainer.get("gpu_name") or ""),
            "cuda_active": bool(trainer.get("cuda_active")),
            "training_steps_total": _safe_int(trainer.get("training_steps_total")),
            "training_steps_last_hour": _safe_int(trainer.get("training_steps_last_hour")),
            "model_id": str(trainer.get("model_id") or ""),
            "input_dim": trainer.get("input_dim"),
            "feature_count": trainer.get("feature_count"),
            "temporal_encoder": str(trainer.get("temporal_encoder") or ""),
            "temporal_encoder_enabled": bool(trainer.get("temporal_encoder_enabled")),
            "effective_trainer_mode": str(trainer.get("effective_trainer_mode") or ""),
            "online_learning_status": str(trainer.get("online_learning_status") or ""),
            "weights_updating": bool(trainer.get("weights_updating")),
            "trainer_process_status": str(trainer.get("trainer_process_status") or ""),
            "backtest_win_rate": _safe_float(trainer.get("backtest_win_rate")) if trainer.get("backtest_win_rate") is not None else None,
            "backtest_expectancy_bps": _safe_float(trainer.get("backtest_expectancy_bps")) if trainer.get("backtest_expectancy_bps") is not None else None,
            "backtest_profit_factor": _safe_float(trainer.get("backtest_profit_factor")) if trainer.get("backtest_profit_factor") is not None else None,
            "throughput_predictions_per_second": _safe_float(trainer.get("throughput_predictions_per_second")) if trainer.get("throughput_predictions_per_second") is not None else None,
            "vram_used_mb": _safe_float(trainer.get("vram_used_mb")) if trainer.get("vram_used_mb") is not None else None,
            "generalization_gap": _safe_float(trainer.get("generalization_gap")) if trainer.get("generalization_gap") is not None else None,
            "validation_loss_delta": _safe_float(trainer.get("validation_loss_delta")) if trainer.get("validation_loss_delta") is not None else None,
        },
        "gpu": {
            "name": str(gpu.get("name") or ""),
            "device": str(gpu.get("device") or ""),
            "utilization_pct": _safe_float(gpu.get("utilization_pct")),
            "vram_used_mb": _safe_int(gpu.get("vram_used_mb")),
            "vram_total_mb": _safe_int(gpu.get("vram_total_mb")),
        },
        "paper": {
            "classification": str(hb.get("classification") or "UNKNOWN"),
            "open_positions": _safe_int(hb.get("open_position_count")),
            "closed_trades": _safe_int(hb.get("closed_trade_count")),
            "realized_pnl_usd": _safe_float(hb.get("realized_pnl_usd")),
            "unrealized_pnl_usd": _safe_float(hb.get("unrealized_pnl_usd")),
            "intents_accepted": _safe_int(hb.get("intents_accepted")),
            "intents_blocked": _safe_int(hb.get("intents_blocked")),
        },
        "risk": {
            "state": str(risk.get("state") or "UNKNOWN"),
            "classification": str(risk.get("classification") or ""),
            "kill_switch_active": bool(risk.get("kill_switch_active", True)),
        },
        "dangerous_controls_require_web_approval": True,
        "mobile_live_trading_blocked": True,
    }
