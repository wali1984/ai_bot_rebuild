from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any, Mapping

from v2.backend.app.services.adaptive_capital_allocator import (
    AllocationInput,
    RiskEnvelope,
    allocate_paper_candidate,
)

from .hedge_plan_simulator import simulate_hedge_plan


SCHEMA_VERSION = "v2_allocator_simulation_packet_v1"
ALLOW_RAW_DECISIONS = {"PASS", "ALLOW", "ALLOWED", "APPROVE", "APPROVED", "ALLOW_WITH_SIZE"}
REJECT_RAW_DECISIONS = {"REJECT", "DENY", "DENIED", "BLOCK", "BLOCKED", "FAIL", "FAILED"}
CONSERVATIVE_PAPER_EQUITY_USD = 1_000.0
CONSERVATIVE_FEE_BPS = 4.0
CONSERVATIVE_SPREAD_BPS = 2.0
CONSERVATIVE_SLIPPAGE_BPS = 2.0
CONSERVATIVE_VOLATILITY_BPS = 80.0
CONSERVATIVE_MAINTENANCE_MARGIN_RATE = 0.005
ALLOCATOR_MARKET_STATE_INTEGRITY_MIN_SCORE = 70.0
ALLOCATOR_MARKET_STATE_INTEGRITY_DEFAULT_SCORE = 70.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "pass", "allow", "allowed"}


def _features(prediction: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = _as_dict(prediction.get("entry_feature_snapshot"))
    features = _as_dict(snapshot.get("features"))
    if not features:
        features = _as_dict(prediction.get("features"))
    return features


def _value(
    row: Mapping[str, Any],
    prediction: Mapping[str, Any],
    *names: str,
) -> Any:
    features = _features(prediction)
    snapshot = _as_dict(prediction.get("entry_feature_snapshot"))
    for name in names:
        value = _first_present(row.get(name), prediction.get(name), features.get(name), snapshot.get(name))
        if value is not None:
            return value
    return None


def _side(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if text in {"buy", "long", "open_long"}:
        return "long"
    if text in {"sell", "short", "open_short"}:
        return "short"
    return None


def _action_side(row: Mapping[str, Any], prediction: Mapping[str, Any]) -> str | None:
    return _side(
        _first_present(
            row.get("side"),
            row.get("action"),
            row.get("selected_action"),
            prediction.get("selected_action"),
            prediction.get("ppo_action"),
            prediction.get("side"),
        )
    )


def _allocator_decision_id(row: Mapping[str, Any], prediction: Mapping[str, Any], generated_utc: str) -> str:
    basis = {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": _first_present(row.get("candidate_id"), prediction.get("candidate_id")),
        "prediction_id": _first_present(row.get("prediction_id"), prediction.get("prediction_id")),
        "symbol": _first_present(row.get("symbol"), prediction.get("symbol")),
        "timeframe": _first_present(row.get("timeframe"), prediction.get("timeframe")),
        "decision_time": _first_present(
            row.get("decision_time"),
            row.get("preemptive_decision_time"),
            prediction.get("decision_time"),
            prediction.get("generated_at"),
            generated_utc,
        ),
    }
    digest = hashlib.sha256(json.dumps(basis, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:24]
    return f"allocsim_{digest}"


def _canonical_margin_mode(value: Any, *, decision: str) -> str:
    if decision == "REJECT":
        return "none"
    text = str(value or "").strip().lower()
    if text.startswith("cross"):
        return "cross_simulated"
    if text.startswith("isolated"):
        return "isolated"
    return "none"


def _canonical_decision(raw: Any) -> str:
    text = str(raw or "").strip().upper()
    if text in ALLOW_RAW_DECISIONS:
        return "PASS"
    if text == "REDUCE_SIZE":
        return "REDUCE_SIZE"
    if text.startswith("BLOCK") or text in REJECT_RAW_DECISIONS:
        return "REJECT"
    if text == "SHADOW_ONLY":
        return "SHADOW_ONLY"
    return "REJECT"


def _base_packet(
    row: Mapping[str, Any],
    prediction: Mapping[str, Any],
    *,
    generated_utc: str,
    decision: str,
    block_reasons: list[str] | None = None,
) -> dict[str, Any]:
    side = _action_side(row, prediction)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "allocator_decision_id": _allocator_decision_id(row, prediction, generated_utc),
        "candidate_id": _first_present(row.get("candidate_id"), prediction.get("candidate_id")),
        "symbol": _first_present(row.get("symbol"), prediction.get("symbol")),
        "timeframe": _first_present(row.get("timeframe"), prediction.get("timeframe")),
        "side": side,
        "decision": decision,
        "allocator_decision": decision,
        "allocator_raw_decision": decision,
        "decision_reason": "allocator_simulation_" + decision.lower(),
        "block_reasons": list(dict.fromkeys(block_reasons or [])),
        "allocator_block_reasons": list(dict.fromkeys(block_reasons or [])),
        "equity_usd": 0.0,
        "available_margin_usd": None,
        "available_margin_source": "missing_signed_read",
        "signed_read_status": "BLOCKED_OPERATOR_KEY_REQUIRED",
        "gross_notional_usd": 0.0,
        "target_notional_usd": 0.0,
        "target_notional_usdt": 0.0,
        "recommended_notional_usd": 0.0,
        "allocated_margin_usd": 0.0,
        "risk_budget_usd": 0.0,
        "recommended_leverage": 0.0,
        "recommended_leverage_source": "adaptive_simulation",
        "recommended_margin_mode": "none",
        "recommended_margin_mode_source": "adaptive_simulation",
        "max_loss_usd": 0.0,
        "expected_max_loss_usd": 0.0,
        "expected_net_pnl_usd": 0.0,
        "expected_fee_usd": 0.0,
        "expected_fees_usd": 0.0,
        "expected_slippage_usd": 0.0,
        "expected_funding_usd": 0.0,
        "liquidation_buffer_usd": 0.0,
        "expected_liquidation_buffer_usd": 0.0,
        "liquidation_buffer_pct": 0.0,
        "maintenance_margin_usd": 0.0,
        "estimated_liquidation_price": None,
        "liquidation_price_estimate": None,
        "distance_to_liquidation_usd": 0.0,
        "liquidation_distance_usd": 0.0,
        "hedge_required": False,
        "hedge_plan": {},
        "exposure_after_trade_usd": 0.0,
        "correlation_after_trade": 0.0,
        "uses_static_leverage": False,
        "uses_static_margin": False,
        "martingale_detected": False,
        "routes_to_live": False,
        "places_real_order": False,
        "order_submitted": False,
        "test_order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
        "allocator_simulation_status": "SIMULATED_CONSERVATIVE_NO_SIGNED_READ",
        "live_ready": False,
    }


def _usd_from_bps(*, notional: float | None, bps: float | None) -> float | None:
    if notional is None or bps is None:
        return None
    return round(abs(notional) * abs(bps) / 10000.0, 8)


def _market_state_integrity_evidence(
    row: Mapping[str, Any],
    prediction: Mapping[str, Any],
) -> tuple[float, float | None, str, bool]:
    explicit_integrity = _float(_value(row, prediction, "market_state_integrity_score"))
    if explicit_integrity is not None:
        score = explicit_integrity * 100.0 if explicit_integrity <= 1.0 else explicit_integrity
        return score, None, "market_state_integrity_score", True

    trust_score = _float(
        _value(
            row,
            prediction,
            "composite_microstructure_trust_score",
            "microstructure_trust_score",
        )
    )
    if trust_score is not None:
        score = trust_score * 100.0 if trust_score <= 1.0 else trust_score
        normalized_trust = trust_score if trust_score <= 1.0 else trust_score / 100.0
        return score, normalized_trust, "microstructure_trust_score", True

    return (
        ALLOCATOR_MARKET_STATE_INTEGRITY_DEFAULT_SCORE,
        None,
        "allocator_default_missing_microstructure_evidence",
        False,
    )


def _existing_packet(
    row: Mapping[str, Any],
    prediction: Mapping[str, Any],
    *,
    generated_utc: str,
    recalculate_incomplete_existing_allocation: bool = False,
) -> dict[str, Any] | None:
    allocation = _as_dict(_first_present(row.get("allocation"), row.get("adaptive_allocation")))
    raw_decision = _first_present(
        row.get("allocator_decision"),
        row.get("allocation_decision"),
        allocation.get("allocator_decision"),
        allocation.get("decision"),
    )
    if raw_decision is None or str(raw_decision).strip().upper() == "MISSING":
        return None
    raw_decision_text = str(raw_decision).strip().upper()
    decision = _canonical_decision(raw_decision)
    notional = _float(
        _first_present(
            row.get("recommended_notional_usd"),
            row.get("gross_notional_usd"),
            row.get("target_notional_usd"),
            row.get("target_notional_usdt"),
            allocation.get("recommended_notional_usd"),
            allocation.get("gross_notional_usd"),
            allocation.get("target_notional_usd"),
            allocation.get("target_notional_usdt"),
            prediction.get("notional_usd"),
        )
    )
    if (
        recalculate_incomplete_existing_allocation
        and decision == "PASS"
        and raw_decision_text in {"ALLOW_WITH_SIZE", "ALLOW", "ALLOWED"}
        and (notional is None or notional <= 0.0)
    ):
        return None
    liquidation_usd = _float(
        _first_present(
            row.get("liquidation_buffer_usd"),
            row.get("expected_liquidation_buffer_usd"),
            allocation.get("liquidation_buffer_usd"),
            allocation.get("liquidation_distance_usd"),
        )
    )
    if liquidation_usd is None:
        liquidation_usd = _usd_from_bps(
            notional=notional,
            bps=_float(_first_present(row.get("liquidation_buffer_bps"), allocation.get("liquidation_buffer_bps"))),
        )
    max_loss = _float(
        _first_present(
            row.get("max_loss_usd"),
            row.get("expected_max_loss_usd"),
            row.get("pre_trade_max_loss_usd"),
            allocation.get("max_loss_usd"),
            allocation.get("max_loss_if_stop_hit"),
        )
    )
    expected_net = _float(
        _first_present(
            row.get("expected_net_pnl_usd"),
            row.get("pre_trade_expected_net_pnl_usd"),
            allocation.get("expected_net_pnl_usd"),
            prediction.get("expected_net_pnl_usd"),
        )
    )
    reasons = [str(reason) for reason in row.get("allocator_block_reasons") or []]
    if max_loss is None:
        reasons.append("ALLOCATOR_MAX_LOSS_USD_MISSING")
    if liquidation_usd is None:
        reasons.append("ALLOCATOR_LIQUIDATION_BUFFER_USD_MISSING")
    if expected_net is None:
        reasons.append("ALLOCATOR_EXPECTED_NET_PNL_USD_MISSING")
    elif expected_net <= 0.0:
        reasons.append("ALLOCATOR_EXPECTED_NET_PNL_USD_NON_POSITIVE")
    if notional is not None and notional <= 0.0:
        reasons.append("ALLOCATOR_TARGET_NOTIONAL_USD_NON_POSITIVE")
        if expected_net is not None and expected_net > 0.0:
            expected_net = 0.0
            reasons.append("ALLOCATOR_EXPECTED_NET_PNL_USD_INVALID_WITH_ZERO_NOTIONAL")
    if reasons and decision == "PASS":
        decision = "REJECT"
    if decision in {"REJECT", "REDUCE_SIZE", "SHADOW_ONLY"} and not reasons:
        reasons.append(f"ALLOCATOR_{str(raw_decision).strip().upper() or decision}")
    recommended_leverage = (
        0.0
        if decision == "REJECT"
        else _float(_first_present(row.get("recommended_leverage"), allocation.get("recommended_leverage"))) or 0.0
    )
    allocated_margin = _float(_first_present(row.get("allocated_margin_usd"), allocation.get("allocated_margin_usd"))) or 0.0
    if allocated_margin <= 0.0 and recommended_leverage > 0.0 and notional is not None and notional > 0.0:
        allocated_margin = round(abs(notional) / recommended_leverage, 8)
    risk_budget = _float(_first_present(row.get("risk_budget_usd"), allocation.get("risk_budget_usd")))
    if risk_budget is None and max_loss is not None and max_loss > 0.0:
        risk_budget = max_loss
    packet = _base_packet(row, prediction, generated_utc=generated_utc, decision=decision, block_reasons=reasons)
    packet.update(
        {
            "allocator_raw_decision": raw_decision,
            "decision_reason": _first_present(allocation.get("final_size_reason"), allocation.get("capital_allocation_reason"), packet["decision_reason"]),
            "equity_usd": _float(_first_present(row.get("equity_usd"), allocation.get("equity_usd"))) or 0.0,
            "available_margin_usd": _float(_first_present(row.get("available_margin_usd"), allocation.get("available_margin_usd"))),
            "gross_notional_usd": notional or 0.0,
            "target_notional_usd": notional or 0.0,
            "target_notional_usdt": notional or 0.0,
            "recommended_notional_usd": notional or 0.0,
            "allocated_margin_usd": allocated_margin,
            "risk_budget_usd": risk_budget or 0.0,
            "recommended_leverage": recommended_leverage,
            "recommended_margin_mode": _canonical_margin_mode(
                _first_present(row.get("recommended_margin_mode"), allocation.get("recommended_margin_mode")),
                decision=decision,
            ),
            "max_loss_usd": max_loss or 0.0,
            "expected_max_loss_usd": max_loss or 0.0,
            "expected_net_pnl_usd": expected_net or 0.0,
            "liquidation_buffer_usd": liquidation_usd or 0.0,
            "expected_liquidation_buffer_usd": liquidation_usd or 0.0,
            "liquidation_buffer_pct": 0.0 if notional in (None, 0.0) else round((liquidation_usd or 0.0) / abs(notional) * 100.0, 8),
            "hedge_required": _bool(_first_present(row.get("hedge_required"), allocation.get("hedge_required"))),
            "hedge_plan": _as_dict(_first_present(row.get("hedge_plan"), allocation.get("hedge_plan"), allocation.get("hedge_exit_plan"))),
        }
    )
    return packet


def _reject_packet(
    row: Mapping[str, Any],
    prediction: Mapping[str, Any],
    *,
    generated_utc: str,
    reasons: list[str],
    expected_net_pnl_usd: float | None = None,
    max_loss_usd: float | None = None,
    liquidation_buffer_usd: float | None = None,
) -> dict[str, Any]:
    packet = _base_packet(row, prediction, generated_utc=generated_utc, decision="REJECT", block_reasons=reasons)
    notional = _float(
        _value(
            row,
            prediction,
            "target_notional_usd",
            "gross_notional_usd",
            "notional_usd",
            "requested_notional_usdt",
        )
    )
    expected_fees = _float(_value(row, prediction, "expected_fees_usd", "expected_fee_usd", "fees_usd"))
    expected_slippage = _float(_value(row, prediction, "expected_slippage_usd", "slippage_usd"))
    expected_funding = _float(_value(row, prediction, "expected_funding_usd", "funding_usd"))
    expected_cost = sum(
        component or 0.0
        for component in (
            expected_fees,
            expected_slippage,
            expected_funding,
            _float(_value(row, prediction, "latency_reserve_usd")),
            _float(_value(row, prediction, "liquidation_risk_reserve_usd")),
            _float(_value(row, prediction, "exit_failure_reserve_usd")),
        )
    )
    (
        market_state_integrity_score,
        microstructure_trust_score,
        market_state_integrity_source,
        market_state_integrity_evidence_present,
    ) = _market_state_integrity_evidence(row, prediction)
    packet.update(
        {
            "decision_reason": "|".join(reasons) if reasons else "allocator_rejected",
            "gross_notional_usd": notional or 0.0,
            "target_notional_usd": notional or 0.0,
            "target_notional_usdt": notional or 0.0,
            "recommended_notional_usd": notional or 0.0,
            "risk_budget_usd": 0.0,
            "expected_net_pnl_usd": expected_net_pnl_usd or 0.0,
            "expected_fee_usd": expected_fees or 0.0,
            "expected_fees_usd": expected_fees or 0.0,
            "expected_slippage_usd": expected_slippage or 0.0,
            "expected_funding_usd": expected_funding or 0.0,
            "expected_cost_usd": round(expected_cost, 8),
            "max_loss_usd": max_loss_usd or 0.0,
            "expected_max_loss_usd": max_loss_usd or 0.0,
            "liquidation_buffer_usd": liquidation_buffer_usd or 0.0,
            "expected_liquidation_buffer_usd": liquidation_buffer_usd or 0.0,
            "market_state_integrity_score": round(market_state_integrity_score, 8),
            "market_state_integrity_minimum_score": ALLOCATOR_MARKET_STATE_INTEGRITY_MIN_SCORE,
            "market_state_integrity_source": market_state_integrity_source,
            "market_state_integrity_evidence_present": market_state_integrity_evidence_present,
            "microstructure_trust_score": None
            if microstructure_trust_score is None
            else round(microstructure_trust_score, 8),
            "hedge_plan": simulate_hedge_plan(
                candidate=packet,
                primary_candidate_passed=False,
                expected_net_pnl_usd=expected_net_pnl_usd,
                max_loss_usd=max_loss_usd,
                liquidation_buffer_usd=liquidation_buffer_usd,
            ),
        }
    )
    return packet


def _economic_edge_bps(
    *,
    row: Mapping[str, Any],
    prediction: Mapping[str, Any],
    side: str,
    notional: float | None,
    expected_net_pnl_usd: float | None,
) -> float | None:
    value = _float(
        _value(
            row,
            prediction,
            "expected_move_after_cost_bps",
            "expected_edge_after_cost_bps",
            "pre_trade_expected_edge_after_cost_bps",
            "edge_after_cost_bps",
        )
    )
    if value is not None:
        if side == "short" and value < 0.0:
            return abs(value)
        return value
    if expected_net_pnl_usd is not None and notional not in (None, 0.0):
        return expected_net_pnl_usd / abs(notional) * 10000.0
    return None


def build_allocator_simulation(
    row: Mapping[str, Any],
    *,
    prediction: Mapping[str, Any] | None = None,
    account_state: Mapping[str, Any] | None = None,
    symbol_filters: Mapping[str, Any] | None = None,
    generated_utc: str | None = None,
    recalculate_incomplete_existing_allocation: bool = False,
) -> dict[str, Any]:
    """Build a canonical allocator packet without live exchange mutation."""
    generated = generated_utc or _utc_now()
    prediction_map = _as_dict(prediction)
    account = _as_dict(account_state)
    filters = _as_dict(symbol_filters)
    existing = _existing_packet(
        row,
        prediction_map,
        generated_utc=generated,
        recalculate_incomplete_existing_allocation=recalculate_incomplete_existing_allocation,
    )
    if existing is not None:
        return existing

    side = _action_side(row, prediction_map)
    symbol = str(_first_present(row.get("symbol"), prediction_map.get("symbol"), "") or "").upper()
    timeframe = str(_first_present(row.get("timeframe"), prediction_map.get("timeframe"), "") or "")
    notional = _float(
        _value(
            row,
            prediction_map,
            "target_notional_usd",
            "gross_notional_usd",
            "notional_usd",
            "requested_notional_usdt",
        )
    )
    expected_net = _float(
        _value(
            row,
            prediction_map,
            "expected_net_pnl_usd",
            "pre_trade_expected_net_pnl_usd",
        )
    )
    if side == "long":
        selected_side_net = _float(_value(row, prediction_map, "long_expected_net_pnl_usd", "expected_long_net_pnl_usd"))
        if selected_side_net is not None:
            expected_net = selected_side_net
    elif side == "short":
        selected_side_net = _float(_value(row, prediction_map, "short_expected_net_pnl_usd", "expected_short_net_pnl_usd"))
        if selected_side_net is not None:
            expected_net = selected_side_net
    max_loss = _float(
        _value(
            row,
            prediction_map,
            "expected_max_loss_usd",
            "max_loss_usd",
            "pre_trade_max_loss_usd",
            "max_loss_if_stop_hit",
        )
    )
    liquidation_usd = _float(_value(row, prediction_map, "expected_liquidation_buffer_usd", "liquidation_buffer_usd"))
    price = _float(
        _value(
            row,
            prediction_map,
            "entry_price",
            "price",
            "price_reference",
            "mark_price",
            "current_price",
            "last_price",
            "close",
        )
    )
    can_size_trade = _first_present(
        row.get("can_size_trade"),
        row.get("current_price_can_size_trade"),
        prediction_map.get("can_size_trade"),
        prediction_map.get("current_price_can_size_trade"),
    )
    pre_trade_loss_probability = _float(_value(row, prediction_map, "pre_trade_loss_probability"))
    # Alt-data confluence context (carried on the row by preemptive edge
    # control). Fail-safe only: can block or shrink, never grow the size.
    altdata_block_score = _float(_value(row, prediction_map, "altdata_trade_block_score"))
    altdata_reduce_score = _float(_value(row, prediction_map, "altdata_reduce_size_score"))
    altdata_hedge_score = _float(_value(row, prediction_map, "altdata_hedge_required_score"))
    altdata_sweep_score = _float(_value(row, prediction_map, "altdata_liquidation_sweep_risk_score"))
    altdata_distribution_score = _float(_value(row, prediction_map, "altdata_wallet_distribution_score"))
    reasons: list[str] = []
    if altdata_block_score is not None and altdata_block_score >= 0.70:
        reasons.append("ALLOCATOR_ALTDATA_TRADE_BLOCK_SCORE_HIGH")
    if not symbol:
        reasons.append("ALLOCATOR_INPUT_SYMBOL_MISSING")
    if not timeframe:
        reasons.append("ALLOCATOR_INPUT_TIMEFRAME_MISSING")
    if side is None:
        reasons.append("ALLOCATOR_INPUT_SIDE_MISSING")
    if price is None or price <= 0.0:
        reasons.append("ALLOCATOR_INPUT_CURRENT_PRICE_MISSING")
    elif can_size_trade is not None and not _bool(can_size_trade):
        reasons.append("ALLOCATOR_CURRENT_PRICE_NOT_TRADE_SIZE_SAFE")
    if expected_net is not None and expected_net <= 0.0:
        reasons.append("ALLOCATOR_EXPECTED_NET_PNL_USD_NON_POSITIVE")
    if pre_trade_loss_probability is None:
        reasons.append("ALLOCATOR_PRE_TRADE_LOSS_PROBABILITY_MISSING")
    elif pre_trade_loss_probability >= 0.80:
        reasons.append("ALLOCATOR_PRE_TRADE_LOSS_PROBABILITY_ABOVE_ALLOWED_BOUND")
    if side is None:
        edge_bps = None
    else:
        edge_bps = _economic_edge_bps(
            row=row,
            prediction=prediction_map,
            side=side,
            notional=notional,
            expected_net_pnl_usd=expected_net,
        )
    if edge_bps is None:
        reasons.append("ALLOCATOR_EXPECTED_EDGE_AFTER_COST_BPS_MISSING")
    elif edge_bps <= 0.0:
        reasons.append("ALLOCATOR_EXPECTED_EDGE_AFTER_COST_BPS_NON_POSITIVE")

    if reasons:
        return _reject_packet(
            row,
            prediction_map,
            generated_utc=generated,
            reasons=list(dict.fromkeys(reasons)),
            expected_net_pnl_usd=expected_net,
            max_loss_usd=max_loss,
            liquidation_buffer_usd=liquidation_usd,
        )

    signed_read_ok = _bool(_first_present(account.get("signed_account_read_ok"), account.get("ok")))
    equity = _float(
        _first_present(
            account.get("equity_usd"),
            account.get("wallet_balance"),
            account.get("available_balance_usd"),
            row.get("equity_usd"),
        )
    )
    available_margin = _float(
        _first_present(
            account.get("available_margin_usd"),
            account.get("available_margin"),
            row.get("available_margin_usd"),
        )
    )
    shadow_equity = equity if equity is not None and equity > 0.0 else CONSERVATIVE_PAPER_EQUITY_USD
    shadow_available = (
        available_margin
        if available_margin is not None and available_margin > 0.0
        else shadow_equity
    )
    spread_bps = _float(_value(row, prediction_map, "spread_bps", "bid_ask_spread_bps")) or CONSERVATIVE_SPREAD_BPS
    slippage_bps = _float(_value(row, prediction_map, "slippage_bps", "expected_slippage_bps", "price_impact_bps")) or CONSERVATIVE_SLIPPAGE_BPS
    fee_bps = _float(_value(row, prediction_map, "fee_bps", "taker_fee_bps")) or CONSERVATIVE_FEE_BPS
    funding_bps = _float(_value(row, prediction_map, "expected_funding_bps", "funding_bps")) or 0.0
    volatility_bps = _float(_value(row, prediction_map, "volatility_bps", "atr_bps", "atr_noise_bps")) or CONSERVATIVE_VOLATILITY_BPS
    liquidity_score = _float(_value(row, prediction_map, "liquidity_score", "market_liquidity_score"))
    if liquidity_score is None:
        liquidity_score = 0.50
    (
        market_state_integrity_score,
        microstructure_score,
        market_state_integrity_source,
        market_state_integrity_evidence_present,
    ) = _market_state_integrity_evidence(row, prediction_map)
    stop_distance_bps = _float(_value(row, prediction_map, "stop_distance_bps", "atr_stop_distance_bps"))
    maintenance_rate = _float(_value(row, prediction_map, "maintenance_margin_rate")) or CONSERVATIVE_MAINTENANCE_MARGIN_RATE
    min_qty = _float(_first_present(filters.get("min_qty"), row.get("min_qty")))
    step_size = _float(_first_present(filters.get("step_size"), row.get("step_size")))
    min_notional = _float(_first_present(filters.get("min_notional"), row.get("min_notional")))
    allocator_edge_bps = edge_bps or 0.0
    if side == "short" and allocator_edge_bps > 0.0:
        allocator_edge_bps = -allocator_edge_bps
    row_input = AllocationInput(
        symbol=symbol,
        timeframe=timeframe,
        action=side or "",
        price=price or 0.0,
        equity=shadow_equity,
        available_margin=shadow_available,
        wallet_balance=shadow_equity,
        confidence_calibrated=_float(_value(row, prediction_map, "confidence", "confidence_calibrated", "calibrated_confidence")) or 0.0,
        expected_move_after_cost_bps=allocator_edge_bps,
        market_state_integrity_score=market_state_integrity_score,
        volatility_bps=volatility_bps,
        liquidity_score=liquidity_score,
        spread_bps=spread_bps,
        slippage_bps=slippage_bps,
        fee_bps=fee_bps,
        expected_funding_bps=funding_bps,
        stop_distance_bps=stop_distance_bps,
        maintenance_margin_rate=maintenance_rate,
        min_qty=min_qty,
        step_size=step_size,
        min_notional=min_notional,
        ppo_action_probability=_float(_value(row, prediction_map, "ppo_action_probability")),
        masa_confidence=_float(_value(row, prediction_map, "masa_confidence")),
        drawdown_bps=_float(_value(row, prediction_map, "drawdown_bps", "current_drawdown_bps")) or 0.0,
        symbol_exposure_usdt=_float(_value(row, prediction_map, "symbol_exposure_usd", "symbol_exposure_usdt")) or 0.0,
        total_exposure_usdt=_float(_value(row, prediction_map, "total_exposure_usd", "total_exposure_usdt")) or 0.0,
        correlation_exposure_pct=_float(_value(row, prediction_map, "correlation_exposure_pct")) or 0.0,
        regime_score=_float(_value(row, prediction_map, "regime_score")) or 1.0,
        lineage_ids={
            "candidate_id": _first_present(row.get("candidate_id"), prediction_map.get("candidate_id")),
            "prediction_id": _first_present(row.get("prediction_id"), prediction_map.get("prediction_id")),
            "signal_id": _first_present(row.get("signal_id"), prediction_map.get("signal_id")),
            "preemptive_decision_id": row.get("preemptive_decision_id"),
            "provider_context": {
                "CoinAnk_features_present": row.get("CoinAnk_features_present"),
                "CoinGlass_features_present": row.get("CoinGlass_features_present"),
                "Moralis_features_present": row.get("Moralis_features_present"),
            },
        },
    )
    result = allocate_paper_candidate(row_input, RiskEnvelope())
    payload = result.to_payload()
    gross_notional_payload = _float(payload.get("gross_notional_usd")) or 0.0
    risk_budget_payload = _float(payload.get("risk_budget_usd")) or 0.0
    raw_decision = payload.get("allocator_decision")
    decision = _canonical_decision(raw_decision)
    block_reasons: list[str] = []
    if decision != "PASS":
        block_reasons.append(f"ALLOCATOR_{str(raw_decision or decision).strip().upper()}")
        if payload.get("final_size_reason"):
            block_reasons.append("ALLOCATOR_" + str(payload["final_size_reason"]).upper())
    liquidation_distance = _float(payload.get("liquidation_distance_usd"))
    max_loss_payload = _float(payload.get("max_loss_usd"))
    expected_net_payload = _float(payload.get("expected_net_pnl_usd"))
    gross_notional_evidence = gross_notional_payload
    if gross_notional_payload <= 0.0:
        if notional is not None and notional > 0.0:
            gross_notional_evidence = notional
            block_reasons.append("ALLOCATOR_OUTPUT_SIZE_ZERO")
        else:
            block_reasons.append("ALLOCATOR_TARGET_NOTIONAL_USD_NON_POSITIVE")
            if expected_net_payload is not None and expected_net_payload > 0.0:
                expected_net_payload = 0.0
                block_reasons.append("ALLOCATOR_EXPECTED_NET_PNL_USD_INVALID_WITH_ZERO_NOTIONAL")
    liquidation_distance_evidence = liquidation_distance if liquidation_distance is not None else liquidation_usd
    max_loss_evidence = max_loss_payload if max_loss_payload is not None else max_loss
    if (max_loss_evidence is None or max_loss_evidence <= 0.0) and max_loss is not None:
        max_loss_evidence = max_loss
    expected_net_evidence = expected_net_payload
    if (expected_net_evidence is None or expected_net_evidence <= 0.0) and expected_net is not None:
        expected_net_evidence = expected_net
    if liquidation_distance_evidence is None:
        block_reasons.append("ALLOCATOR_LIQUIDATION_BUFFER_USD_MISSING")
    if max_loss_evidence is None:
        block_reasons.append("ALLOCATOR_MAX_LOSS_USD_MISSING")
    if expected_net_evidence is not None and expected_net_evidence <= 0.0:
        block_reasons.append("ALLOCATOR_EXPECTED_NET_PNL_USD_NON_POSITIVE")
    if block_reasons and decision == "PASS":
        decision = "REJECT"
    hedge_plan = simulate_hedge_plan(
        candidate={
            "symbol": symbol,
            "side": side,
            "target_notional_usd": gross_notional_payload,
            "gross_notional_usd": gross_notional_payload,
        },
        positions=account.get("current_positions") if isinstance(account.get("current_positions"), list) else (),
        equity_usd=shadow_equity,
        risk_budget_usd=_float(payload.get("risk_budget_usd")) or 0.0,
        hedge_budget_usd=_float(payload.get("hedge_budget_usd")) or 0.0,
        max_loss_usd=max_loss_evidence,
        expected_net_pnl_usd=expected_net_evidence,
        liquidation_buffer_usd=liquidation_distance_evidence,
        spread_bps=spread_bps,
        slippage_bps=slippage_bps,
        fee_bps=fee_bps,
        funding_bps=funding_bps,
        correlation_exposure_pct=_float(payload.get("correlation_exposure_after_trade")),
        primary_candidate_passed=decision == "PASS",
        hedge_mode_supported=_bool(_first_present(account.get("hedge_mode"), account.get("dual_side_position"))),
    )
    gross_notional = gross_notional_evidence
    loss_probability_size_factor = 1.0
    loss_probability_size_reasons: list[str] = []
    if (
        pre_trade_loss_probability is not None
        and 0.60 <= pre_trade_loss_probability < 0.80
        and gross_notional > 0.0
    ):
        loss_pressure = min(1.0, max(0.0, (pre_trade_loss_probability - 0.50) / 0.30))
        loss_probability_size_factor = round(max(0.35, 1.0 - (0.55 * loss_pressure)), 8)
        gross_notional = round(gross_notional * loss_probability_size_factor, 8)
        loss_probability_size_reasons.append("PRE_TRADE_LOSS_PROBABILITY_ELEVATED_CONSERVATIVE_SIZING")
    altdata_size_factor = 1.0
    altdata_size_reasons: list[str] = []
    if altdata_reduce_score is not None and altdata_reduce_score >= 0.50:
        altdata_size_factor *= max(0.25, 1.0 - min(altdata_reduce_score, 0.75))
        altdata_size_reasons.append("ALTDATA_REDUCE_SIZE_SCORE_ELEVATED")
    if altdata_sweep_score is not None and altdata_sweep_score >= 0.70:
        altdata_size_factor *= 0.50
        altdata_size_reasons.append("ALTDATA_LIQUIDATION_SWEEP_RISK_CONSERVATIVE_SIZING")
    if (
        altdata_distribution_score is not None
        and altdata_distribution_score >= 0.60
        and (side or "") == "long"
    ):
        altdata_size_factor = min(altdata_size_factor, 1.0)
        altdata_size_reasons.append("ALTDATA_DISTRIBUTION_CONFLICT_NO_SIZE_INCREASE")
    if altdata_size_factor < 1.0 and gross_notional > 0.0:
        gross_notional = round(gross_notional * altdata_size_factor, 8)
    altdata_hedge_required = altdata_hedge_score is not None and altdata_hedge_score >= 0.50
    maintenance_margin = _float(payload.get("maintenance_margin_estimate_usd")) or gross_notional * maintenance_rate
    recommended_leverage_evidence = _float(payload.get("recommended_leverage")) if decision != "REJECT" else 0.0
    allocated_margin_evidence = _float(payload.get("allocated_margin_usd")) or 0.0
    if recommended_leverage_evidence and recommended_leverage_evidence > 0.0 and gross_notional > 0.0:
        allocated_margin_evidence = round(gross_notional / recommended_leverage_evidence, 8)
    expected_fees_evidence = _float(payload.get("expected_fees_usd"))
    if expected_fees_evidence is None or expected_fees_evidence == 0.0:
        expected_fees_evidence = _float(_value(row, prediction_map, "expected_fees_usd", "expected_fee_usd", "fees_usd")) or 0.0
    expected_slippage_evidence = _float(payload.get("expected_slippage_usd"))
    if expected_slippage_evidence is None or expected_slippage_evidence == 0.0:
        expected_slippage_evidence = _float(_value(row, prediction_map, "expected_slippage_usd", "slippage_usd")) or 0.0
    expected_funding_evidence = _float(payload.get("expected_funding_usd"))
    if expected_funding_evidence is None or expected_funding_evidence == 0.0:
        expected_funding_evidence = _float(_value(row, prediction_map, "expected_funding_usd", "funding_usd")) or 0.0
    packet = _base_packet(
        row,
        prediction_map,
        generated_utc=generated,
        decision=decision,
        block_reasons=list(dict.fromkeys(block_reasons)),
    )
    packet.update(
        {
            "allocator_raw_decision": raw_decision,
            "decision_reason": _first_present(payload.get("final_size_reason"), payload.get("capital_allocation_reason"), packet["decision_reason"]),
            "equity_usd": round(shadow_equity, 8),
            "equity_source": "signed_read" if equity is not None and signed_read_ok else "paper_simulation_default_no_signed_read",
            "available_margin_usd": available_margin if signed_read_ok else None,
            "available_margin_source": "signed_read" if available_margin is not None and signed_read_ok else "missing_signed_read_shadow_margin_used_for_paper_only",
            "signed_read_status": "PASS" if signed_read_ok else "BLOCKED_OPERATOR_KEY_REQUIRED",
            "paper_simulation_available_margin_usd": round(shadow_available, 8),
            "gross_notional_usd": gross_notional,
            "target_notional_usd": gross_notional,
            "target_notional_usdt": gross_notional,
            "recommended_notional_usd": gross_notional,
            "allocated_margin_usd": allocated_margin_evidence,
            "risk_budget_usd": risk_budget_payload,
            "recommended_leverage": recommended_leverage_evidence,
            "recommended_margin_mode": _canonical_margin_mode(payload.get("recommended_margin_mode"), decision=decision),
            "max_loss_usd": max_loss_evidence or 0.0,
            "expected_max_loss_usd": max_loss_evidence or 0.0,
            "expected_net_pnl_usd": expected_net_evidence or 0.0,
            "expected_fee_usd": expected_fees_evidence,
            "expected_fees_usd": expected_fees_evidence,
            "expected_slippage_usd": expected_slippage_evidence,
            "expected_funding_usd": expected_funding_evidence,
            "liquidation_buffer_usd": liquidation_distance_evidence or 0.0,
            "expected_liquidation_buffer_usd": liquidation_distance_evidence or 0.0,
            "liquidation_buffer_pct": 0.0 if gross_notional <= 0.0 else round((liquidation_distance_evidence or 0.0) / gross_notional * 100.0, 8),
            "maintenance_margin_usd": round(maintenance_margin, 8),
            "market_state_integrity_score": round(market_state_integrity_score, 8),
            "market_state_integrity_minimum_score": ALLOCATOR_MARKET_STATE_INTEGRITY_MIN_SCORE,
            "market_state_integrity_source": market_state_integrity_source,
            "market_state_integrity_evidence_present": market_state_integrity_evidence_present,
            "microstructure_trust_score": None
            if microstructure_score is None
            else round(microstructure_score, 8),
            "estimated_liquidation_price": payload.get("liquidation_price_estimate"),
            "liquidation_price_estimate": payload.get("liquidation_price_estimate"),
            "distance_to_liquidation_usd": liquidation_distance_evidence or 0.0,
            "liquidation_distance_usd": liquidation_distance_evidence or 0.0,
            "hedge_required": bool(hedge_plan.get("hedge_required")) or altdata_hedge_required,
            "hedge_plan": hedge_plan,
            "loss_probability_size_factor": loss_probability_size_factor,
            "loss_probability_size_reasons": loss_probability_size_reasons,
            "altdata_hedge_required": altdata_hedge_required,
            "altdata_size_factor": altdata_size_factor,
            "altdata_size_reasons": altdata_size_reasons,
            "altdata_trade_block_score": altdata_block_score,
            "altdata_reduce_size_score": altdata_reduce_score,
            "altdata_hedge_required_score": altdata_hedge_score,
            "altdata_liquidation_sweep_risk_score": altdata_sweep_score,
            "altdata_wallet_distribution_score": altdata_distribution_score,
            "provider_features_used": [
                name
                for name, value in (
                    ("altdata_trade_block_score", altdata_block_score),
                    ("altdata_reduce_size_score", altdata_reduce_score),
                    ("altdata_hedge_required_score", altdata_hedge_score),
                    ("altdata_liquidation_sweep_risk_score", altdata_sweep_score),
                    ("altdata_wallet_distribution_score", altdata_distribution_score),
                )
                if value is not None
            ],
            "provider_features_missing": [
                name
                for name, value in (
                    ("altdata_trade_block_score", altdata_block_score),
                    ("altdata_reduce_size_score", altdata_reduce_score),
                    ("altdata_hedge_required_score", altdata_hedge_score),
                    ("altdata_liquidation_sweep_risk_score", altdata_sweep_score),
                    ("altdata_wallet_distribution_score", altdata_distribution_score),
                )
                if value is None
            ],
            "exposure_after_trade_usd": _float(payload.get("portfolio_exposure_after_trade")) or 0.0,
            "correlation_after_trade": _float(payload.get("correlation_exposure_after_trade")) or 0.0,
            "allocator_simulation_status": "SIMULATED_CONSERVATIVE_NO_SIGNED_READ" if not signed_read_ok else "SIMULATED_WITH_SIGNED_READ_ACCOUNT_STATE",
            "model_inputs": payload.get("model_inputs") or {},
        }
    )
    return packet
