"""Read-only Phase 7 real-trader readiness helpers.

These helpers build operator-review payloads from already collected snapshots.
They do not hold an exchange client, submit/test/cancel/modify orders, mutate
leverage or margin mode, write Redis, or restart services.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Mapping

from .exchange_filter_sizing import min_executable_order
from .live_position_state_machine import LiveCanaryConfig, reconcile_exchange_local_state, validate_position_transition


SCHEMA_VERSION = "phase7_real_trader_readiness_v1"
LIVE_GATE_ENABLED = "enabled_operator_approved"
LIVE_GATE_BLOCKED = "blocked_human_only"
OPERATOR_GATE_BLOCKERS = frozenset({"LIVE_GATE_NOT_ENABLED", "RELEASE_MODE_NON_LIVE", "OPERATOR_APPROVAL_REQUIRED"})
ALLOW_ALLOCATOR_DECISIONS = frozenset({"ALLOW_WITH_SIZE", "REDUCE_SIZE"})
HARD_SAFETY_FALSE_FLAGS = (
    "order_submitted",
    "test_order_submitted",
    "exchange_leverage_mutated",
    "exchange_margin_mutated",
    "places_real_order",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _epoch_ms(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp() * 1000.0


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "allow", "allowed", "approved"}


def _safety_flags() -> dict[str, bool]:
    return {field: False for field in HARD_SAFETY_FALSE_FLAGS}


def _canonical_side(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"buy", "long", "open_long", "long_open"}:
        return "BUY"
    if text in {"sell", "short", "open_short", "short_open"}:
        return "SELL"
    return str(value or "").strip().upper()


def _canonical_action(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"buy", "long", "open_long", "long_open"}:
        return "long"
    if text in {"sell", "short", "open_short", "short_open"}:
        return "short"
    if text in {"close_long", "long_close", "sell_reduce"}:
        return "close_long"
    if text in {"close_short", "short_close", "buy_reduce"}:
        return "close_short"
    return text


def _candidate_summary(allocation_payload: Mapping[str, Any] | None, candidate_signal: Mapping[str, Any] | None) -> dict[str, Any]:
    allocation = _as_dict(allocation_payload)
    signal = _as_dict(candidate_signal)
    action = _canonical_action(_first_present(allocation.get("action"), signal.get("action"), signal.get("side")))
    symbol = str(_first_present(allocation.get("symbol"), signal.get("symbol"), "") or "").upper()
    quantity = _float(
        _first_present(
            allocation.get("target_quantity"),
            allocation.get("quantity"),
            signal.get("requested_quantity"),
            signal.get("quantity"),
        )
    )
    notional = _float(
        _first_present(
            allocation.get("target_notional_usd"),
            allocation.get("target_notional_usdt"),
            allocation.get("gross_notional_usd"),
            signal.get("requested_notional_usdt"),
            signal.get("notional"),
        )
    )
    return {
        "symbol": symbol,
        "side": _canonical_side(_first_present(allocation.get("side"), signal.get("side"), action)),
        "action": action,
        "quantity": quantity,
        "notional": notional,
        "margin": _float(_first_present(allocation.get("allocated_margin_usd"), signal.get("allocated_margin_usd"))),
        "leverage_recommendation": _float(allocation.get("recommended_leverage")),
        "margin_mode_recommendation": _first_present(allocation.get("recommended_margin_mode"), signal.get("margin_mode")),
        "stop_distance_bps": _float(allocation.get("stop_distance_bps")),
        "max_loss": _float(allocation.get("max_loss_if_stop_hit")),
        "liquidation_buffer_bps": _float(allocation.get("liquidation_buffer_bps")),
        "risk_reward": _float(allocation.get("risk_reward")),
        "risk_of_ruin_contribution": _float(allocation.get("risk_of_ruin_contribution")),
        "expected_net_pnl_usd": _float(allocation.get("expected_net_pnl_usd")),
        "allocator_decision": _first_present(allocation.get("allocator_decision"), allocation.get("decision")),
        "lineage_ids": _as_dict(allocation.get("lineage_ids")),
    }


def _risk_profile_fields(runtime_payload: Mapping[str, Any]) -> dict[str, Any]:
    profile = _as_dict(runtime_payload.get("risk_profile"))
    return _as_dict(profile.get("fields"))


def _live_canary_config(runtime_payload: Mapping[str, Any]) -> LiveCanaryConfig:
    explicit = runtime_payload.get("live_canary_config") or runtime_payload.get("live_canary")
    if isinstance(explicit, Mapping):
        return LiveCanaryConfig.from_mapping(explicit)
    fields = _risk_profile_fields(runtime_payload)
    max_notional = _float(_first_present(fields.get("max_notional_per_trade"), fields.get("max_symbol_exposure")))
    max_daily_loss = _float(_first_present(fields.get("max_daily_loss"), fields.get("max_daily_loss_usd")))
    max_open_positions = int(_float(fields.get("max_open_positions")) or 1)
    allowed_symbols = tuple(
        str(symbol).upper()
        for symbol in (
            runtime_payload.get("accepted_live_symbols")
            or runtime_payload.get("live_symbols")
            or runtime_payload.get("execution_live_symbols")
            or []
        )
        if str(symbol).strip()
    )
    return LiveCanaryConfig(
        live_canary_enabled=runtime_payload.get("live_gate") == LIVE_GATE_ENABLED,
        allowed_symbols=allowed_symbols,
        max_open_positions=max_open_positions,
        max_notional_usd=float(max_notional if max_notional is not None else 10.0),
        max_daily_loss_usd=float(max_daily_loss if max_daily_loss is not None else 10.0),
    )


def _symbol_filter_for_candidate(symbol_filter_snapshot: Mapping[str, Any] | None, symbol: str) -> dict[str, Any]:
    snapshot = _as_dict(symbol_filter_snapshot)
    if not snapshot:
        return {}
    by_symbol = snapshot.get(symbol)
    if isinstance(by_symbol, Mapping):
        return dict(by_symbol)
    filters = snapshot.get("filters")
    if isinstance(filters, Mapping) and isinstance(filters.get(symbol), Mapping):
        return dict(filters[symbol])
    if snapshot.get("symbol") in (None, "", symbol) or any(
        key in snapshot for key in ("min_qty", "step_size", "tick_size", "min_notional")
    ):
        return snapshot
    return {}


def _position_for_symbol(rows: Any, symbol: str) -> dict[str, Any]:
    if isinstance(rows, Mapping):
        if rows.get("symbol") in (None, "", symbol):
            return dict(rows)
        nested = rows.get(symbol)
        if isinstance(nested, Mapping):
            return dict(nested)
    for row in _as_list(rows):
        if isinstance(row, Mapping) and str(row.get("symbol") or "").upper() == symbol:
            return dict(row)
    return {}


def build_live_kill_switch_status(
    runtime_payload: Mapping[str, Any] | None,
    *,
    operator_truth: Mapping[str, Any] | None = None,
    generated_utc: str | None = None,
) -> dict[str, Any]:
    runtime = _as_dict(runtime_payload)
    truth = _as_dict(operator_truth)
    enabled_value = _first_present(runtime.get("kill_switch_enabled"), truth.get("kill_switch_enabled"))
    active = _bool(_first_present(runtime.get("kill_switch_active"), truth.get("kill_switch_active")))
    blockers: list[str] = []
    if enabled_value is None:
        blockers.append("KILL_SWITCH_ENABLEMENT_UNKNOWN")
    elif not _bool(enabled_value):
        blockers.append("KILL_SWITCH_NOT_ENABLED")
    if active:
        blockers.append("KILL_SWITCH_ACTIVE")
    status = "LIVE_KILL_SWITCH_CLEAR" if not blockers else "LIVE_KILL_SWITCH_BLOCKED"
    return {
        "schema_version": f"{SCHEMA_VERSION}_kill_switch",
        "generated_utc": generated_utc or _utc_now(),
        "status": status,
        "kill_switch_enabled": _bool(enabled_value),
        "kill_switch_active": active,
        "blockers": list(dict.fromkeys(blockers)),
        "no_live_mutation": True,
        **_safety_flags(),
    }


def build_live_position_reconciliation_status(
    runtime_payload: Mapping[str, Any] | None,
    *,
    account_snapshot: Mapping[str, Any] | None = None,
    candidate: Mapping[str, Any] | None = None,
    generated_utc: str | None = None,
    now_ms: int | float | None = None,
) -> dict[str, Any]:
    runtime = _as_dict(runtime_payload)
    account = _as_dict(account_snapshot)
    candidate_record = _as_dict(candidate)
    position_mode_snapshot = _as_dict(account.get("position_mode_snapshot"))
    open_orders_snapshot = _as_dict(account.get("open_orders_snapshot"))
    symbol = str(_first_present(candidate_record.get("symbol"), account.get("symbol"), "") or "").upper()
    signed_ok = _bool(_first_present(account.get("signed_account_read_ok"), account.get("ok")))
    local_position = _as_dict(
        _first_present(
            account.get("local_position"),
            runtime.get("local_position"),
            runtime.get("current_position"),
        )
    )
    exchange_position = _as_dict(
        _first_present(
            account.get("exchange_position"),
            _position_for_symbol(account.get("current_positions"), symbol),
            _position_for_symbol(account.get("positions"), symbol),
            runtime.get("exchange_position"),
        )
    )
    open_orders_value = _first_present(account.get("open_orders"), open_orders_snapshot.get("open_orders"), runtime.get("open_orders"))
    if open_orders_value is None and open_orders_snapshot.get("ok") is True and open_orders_snapshot.get("open_orders_count") == 0:
        open_orders_value = []
    open_orders = [dict(item) for item in _as_list(open_orders_value) if isinstance(item, Mapping)]
    hedge_mode = _first_present(
        account.get("hedge_mode"),
        account.get("dual_side_position"),
        position_mode_snapshot.get("hedge_mode"),
        position_mode_snapshot.get("dual_side_position"),
        runtime.get("hedge_mode"),
    )
    margin_mode = _first_present(account.get("margin_mode"), position_mode_snapshot.get("margin_mode"), runtime.get("margin_mode"))
    signed_read_ts_ms = _float(
        _first_present(
            account.get("signed_read_ts_ms"),
            account.get("account_read_ts_ms"),
            account.get("position_read_ts_ms"),
            _epoch_ms(account.get("generated_est")),
            _epoch_ms(account.get("signed_read_generated_est")),
        )
    )
    reconciliation = reconcile_exchange_local_state(
        exchange_position=exchange_position,
        local_position=local_position,
        open_orders=open_orders,
        hedge_mode=hedge_mode if hedge_mode is None else _bool(hedge_mode),
        margin_mode=str(margin_mode or ""),
        signed_read_ts_ms=signed_read_ts_ms,
        now_ms=now_ms,
        config=_live_canary_config(runtime),
    )
    blockers = list(reconciliation.get("blockers") or [])
    if not signed_ok:
        blockers.insert(0, "SIGNED_ACCOUNT_READ_MISSING")
    if account.get("fresh") is False or account.get("signed_read_fresh") is False:
        blockers.insert(0, "SIGNED_READ_STALE")
    if open_orders_snapshot and open_orders_snapshot.get("fresh") is False:
        blockers.append("OPEN_ORDERS_SNAPSHOT_STALE")
    if open_orders_snapshot and open_orders_snapshot.get("ok") is not True:
        blockers.append("OPEN_ORDERS_READ_MISSING")
    if position_mode_snapshot and position_mode_snapshot.get("fresh") is False:
        blockers.append("POSITION_MODE_SNAPSHOT_STALE")
    if position_mode_snapshot and position_mode_snapshot.get("ok") is not True:
        blockers.append("POSITION_MODE_READ_MISSING")
    if not symbol:
        blockers.append("CANDIDATE_SYMBOL_MISSING")
    unique = list(dict.fromkeys(str(item) for item in blockers if str(item)))
    return {
        "schema_version": f"{SCHEMA_VERSION}_position_reconciliation",
        "generated_utc": generated_utc or _utc_now(),
        "status": "LIVE_POSITION_RECONCILED" if not unique else "LIVE_POSITION_RECONCILIATION_BLOCKED",
        "reconciled": not unique,
        "signed_account_read_ok": signed_ok,
        "candidate_symbol": symbol,
        "exchange_local_reconciliation": reconciliation,
        "blockers": unique,
        "no_live_mutation": True,
        **_safety_flags(),
    }


def build_live_pre_submit_dry_run_status(
    runtime_payload: Mapping[str, Any] | None,
    *,
    operator_truth: Mapping[str, Any] | None = None,
    account_snapshot: Mapping[str, Any] | None = None,
    symbol_filter_snapshot: Mapping[str, Any] | None = None,
    allocation_payload: Mapping[str, Any] | None = None,
    candidate_signal: Mapping[str, Any] | None = None,
    generated_utc: str | None = None,
    now_ms: int | float | None = None,
) -> dict[str, Any]:
    runtime = _as_dict(runtime_payload)
    truth = _as_dict(operator_truth)
    account = _as_dict(account_snapshot)
    allocation = _as_dict(allocation_payload)
    candidate = _candidate_summary(allocation, candidate_signal)
    filters = _symbol_filter_for_candidate(symbol_filter_snapshot, str(candidate.get("symbol") or ""))
    filter_snapshot = _as_dict(symbol_filter_snapshot)
    fields = _risk_profile_fields(runtime)
    blockers: list[str] = []
    warnings: list[str] = []

    live_gate = _first_present(runtime.get("live_gate"), truth.get("live_gate"))
    release_mode = str(_first_present(runtime.get("release_mode"), truth.get("release_mode"), "NON_LIVE") or "NON_LIVE").upper()
    if live_gate != LIVE_GATE_ENABLED:
        blockers.append("LIVE_GATE_NOT_ENABLED")
    if release_mode != "LIVE_CANARY_APPROVED":
        blockers.append("RELEASE_MODE_NON_LIVE")
    if runtime.get("operator_approved") is not True:
        blockers.append("OPERATOR_APPROVAL_REQUIRED")
    if runtime.get("places_real_order") is True or truth.get("places_real_order") is True:
        blockers.append("RUNTIME_ALREADY_MARKS_REAL_ORDER")
    if runtime.get("exchange_action_taken") is True or truth.get("exchange_action_taken") is True:
        blockers.append("RUNTIME_EXCHANGE_ACTION_ALREADY_TAKEN")
    if _bool(_first_present(runtime.get("leverage_mutation_allowed"), truth.get("leverage_mutation_allowed"))):
        warnings.append("LEVERAGE_MUTATION_ALLOWED_FLAG_TRUE_IN_RUNTIME")
    if _bool(_first_present(runtime.get("margin_mutation_allowed"), truth.get("margin_mutation_allowed"))):
        warnings.append("MARGIN_MUTATION_ALLOWED_FLAG_TRUE_IN_RUNTIME")

    kill_switch = build_live_kill_switch_status(runtime, operator_truth=truth, generated_utc=generated_utc)
    blockers.extend(kill_switch["blockers"])

    if not candidate.get("symbol"):
        blockers.append("CANDIDATE_SYMBOL_MISSING")
    if candidate.get("side") not in {"BUY", "SELL"}:
        blockers.append("CANDIDATE_SIDE_MISSING")
    if (_float(candidate.get("quantity")) or 0.0) <= 0.0:
        blockers.append("CANDIDATE_QUANTITY_NOT_POSITIVE")
    if (_float(candidate.get("notional")) or 0.0) <= 0.0:
        blockers.append("CANDIDATE_NOTIONAL_NOT_POSITIVE")
    if str(candidate.get("allocator_decision") or "") not in ALLOW_ALLOCATOR_DECISIONS:
        blockers.append("LIVE_PRE_SUBMIT_ALLOCATOR_NOT_ALLOWING_SIZE")

    available_margin = _float(_first_present(account.get("available_margin"), runtime.get("available_margin"), truth.get("available_margin")))
    required_margin = _float(_first_present(candidate.get("margin"), runtime.get("required_initial_margin"), truth.get("required_initial_margin")))
    if not _bool(_first_present(account.get("signed_account_read_ok"), account.get("ok"))):
        blockers.append("SIGNED_ACCOUNT_READ_MISSING")
    if account.get("fresh") is False or account.get("signed_read_fresh") is False:
        blockers.append("SIGNED_READ_STALE")
    if available_margin is None:
        blockers.append("AVAILABLE_MARGIN_MISSING")
    elif required_margin is not None and available_margin < required_margin:
        blockers.append("AVAILABLE_MARGIN_BELOW_REQUIRED_INITIAL_MARGIN")

    if filters.get("ok") is not True:
        blockers.append("SYMBOL_FILTERS_NOT_VERIFIED")
    if filter_snapshot.get("fresh") is False:
        blockers.append("SYMBOL_FILTERS_STALE")
    if not filters.get("min_notional"):
        blockers.append("MIN_NOTIONAL_MISSING")
    if not filters.get("step_size"):
        blockers.append("STEP_SIZE_MISSING")
    if not filters.get("tick_size"):
        blockers.append("TICK_SIZE_MISSING")
    if filters and filters.get("ok") is True:
        sizing = min_executable_order(
            mark_price=_first_present(
                allocation.get("price"),
                allocation.get("price_reference"),
                candidate_signal and candidate_signal.get("price"),
                candidate_signal and candidate_signal.get("price_reference"),
            ),
            min_notional=filters.get("min_notional"),
            min_qty=filters.get("min_qty"),
            step_size=filters.get("step_size"),
        )
        filters["min_executable_order"] = sizing
        min_executable_notional = _float(sizing.get("min_executable_notional"))
        if sizing.get("ok") is not True:
            blockers.extend(f"MIN_EXECUTABLE:{reason}" for reason in sizing.get("blockers", []))
        elif min_executable_notional is not None and (_float(candidate.get("notional")) or 0.0) < min_executable_notional:
            blockers.append("CANDIDATE_NOTIONAL_BELOW_MIN_EXECUTABLE")

    max_symbol_exposure = _float(fields.get("max_symbol_exposure"))
    max_total_exposure = _float(fields.get("max_total_exposure"))
    max_drawdown = _float(fields.get("max_drawdown"))
    symbol_exposure_after = _float(
        _first_present(allocation.get("symbol_exposure_after_trade"), allocation.get("target_notional_usd"), candidate.get("notional"))
    )
    total_exposure_after = _float(_first_present(allocation.get("portfolio_exposure_after_trade"), candidate.get("notional")))
    current_drawdown = _float(fields.get("current_drawdown_bps")) or _float(runtime.get("current_drawdown_bps")) or 0.0
    if max_symbol_exposure is not None and symbol_exposure_after is not None and symbol_exposure_after > max_symbol_exposure:
        blockers.append("PER_SYMBOL_EXPOSURE_CAP_EXCEEDED")
    if max_total_exposure is not None and total_exposure_after is not None and total_exposure_after > max_total_exposure:
        blockers.append("TOTAL_EXPOSURE_CAP_EXCEEDED")
    if max_drawdown is not None and current_drawdown > max_drawdown:
        blockers.append("DRAWDOWN_CAP_EXCEEDED")

    position_status = build_live_position_reconciliation_status(
        runtime,
        account_snapshot=account,
        candidate=candidate,
        generated_utc=generated_utc,
        now_ms=now_ms,
    )
    blockers.extend(position_status["blockers"])
    transition = validate_position_transition(
        local_position=_as_dict(_first_present(account.get("local_position"), runtime.get("local_position"), {"side": "flat", "quantity": 0})),
        exchange_position=_as_dict(
            _first_present(
                account.get("exchange_position"),
                _position_for_symbol(account.get("current_positions"), str(candidate.get("symbol") or "")),
                {"side": "flat", "quantity": 0},
            )
        ),
        requested_action=str(candidate.get("action") or ""),
        symbol=str(candidate.get("symbol") or ""),
        quantity=float(_float(candidate.get("quantity")) or 0.0),
        notional_usd=float(_float(candidate.get("notional")) or 0.0),
        reduce_only=_bool(_first_present(candidate_signal and candidate_signal.get("reduce_only"), allocation.get("reduce_only"))),
        config=_live_canary_config(runtime),
        open_positions_count=int(_float(runtime.get("open_positions_count")) or 0),
    )
    blockers.extend(transition.blockers)

    unique = list(dict.fromkeys(str(item) for item in blockers if str(item)))
    non_operator_blockers = [item for item in unique if item not in OPERATOR_GATE_BLOCKERS]
    would_submit_if_operator_approved = not non_operator_blockers
    submit_allowed = not unique
    pass_conditions = {
        "dry_run_only": True,
        "live_gate_enabled": live_gate == LIVE_GATE_ENABLED,
        "release_mode_approved": release_mode == "LIVE_CANARY_APPROVED",
        "signed_account_read_ok": "SIGNED_ACCOUNT_READ_MISSING" not in unique,
        "available_margin_check_pass": "AVAILABLE_MARGIN_BELOW_REQUIRED_INITIAL_MARGIN" not in unique
        and "AVAILABLE_MARGIN_MISSING" not in unique,
        "position_reconciled": position_status["reconciled"],
        "open_orders_clear": "UNEXPECTED_OPEN_EXCHANGE_ORDERS" not in unique,
        "symbol_filters_verified": "SYMBOL_FILTERS_NOT_VERIFIED" not in unique and "SYMBOL_FILTERS_STALE" not in unique,
        "min_notional_verified": "MIN_NOTIONAL_MISSING" not in unique
        and "CANDIDATE_NOTIONAL_BELOW_MIN_EXECUTABLE" not in unique
        and "SYMBOL_FILTERS_STALE" not in unique,
        "step_size_verified": "STEP_SIZE_MISSING" not in unique and "SYMBOL_FILTERS_STALE" not in unique,
        "tick_size_verified": "TICK_SIZE_MISSING" not in unique and "SYMBOL_FILTERS_STALE" not in unique,
        "allocator_allows_size": "LIVE_PRE_SUBMIT_ALLOCATOR_NOT_ALLOWING_SIZE" not in unique,
        "per_symbol_exposure_cap_pass": "PER_SYMBOL_EXPOSURE_CAP_EXCEEDED" not in unique,
        "total_exposure_cap_pass": "TOTAL_EXPOSURE_CAP_EXCEEDED" not in unique,
        "drawdown_cap_pass": "DRAWDOWN_CAP_EXCEEDED" not in unique,
        "kill_switch_clear": kill_switch["status"] == "LIVE_KILL_SWITCH_CLEAR",
        "position_transition_valid": transition.allowed,
        "hard_safety_no_mutation": True,
    }
    return {
        "schema_version": f"{SCHEMA_VERSION}_pre_submit_dry_run",
        "generated_utc": generated_utc or _utc_now(),
        "status": "LIVE_PRE_SUBMIT_DRY_RUN_READY" if submit_allowed else "LIVE_PRE_SUBMIT_DRY_RUN_BLOCKED",
        "dry_run": True,
        "submit_allowed": submit_allowed,
        "would_submit_if_operator_approved": would_submit_if_operator_approved,
        "operator_review_ready": would_submit_if_operator_approved,
        "live_gate": live_gate,
        "release_mode": release_mode,
        "candidate": candidate,
        "symbol_filter_status": filters,
        "kill_switch_status": kill_switch,
        "position_reconciliation_status": position_status,
        "position_transition": transition.to_dict(),
        "pass_conditions": pass_conditions,
        "warnings": sorted(set(warnings)),
        "blockers": unique,
        "non_operator_blockers": non_operator_blockers,
        "no_live_mutation": True,
        **_safety_flags(),
    }


def build_first_live_canary_operator_packet(
    pre_submit_status: Mapping[str, Any],
    *,
    allocation_payload: Mapping[str, Any] | None = None,
    candidate_signal: Mapping[str, Any] | None = None,
    generated_utc: str | None = None,
) -> dict[str, Any]:
    pre_submit = _as_dict(pre_submit_status)
    candidate = _as_dict(pre_submit.get("candidate")) or _candidate_summary(allocation_payload, candidate_signal)
    blockers = [str(item) for item in _as_list(pre_submit.get("blockers")) if str(item)]
    allowed_reasons = [
        "dry_run_only_no_exchange_submit",
        "hard_safety_flags_false",
    ]
    if pre_submit.get("operator_review_ready") is True:
        allowed_reasons.append("all_non_operator_pre_submit_checks_pass")
    return {
        "schema_version": f"{SCHEMA_VERSION}_first_live_canary_operator_packet",
        "generated_utc": generated_utc or _utc_now(),
        "status": "FIRST_LIVE_CANARY_PACKET_READY_FOR_OPERATOR_REVIEW"
        if pre_submit.get("operator_review_ready") is True
        else "FIRST_LIVE_CANARY_PACKET_BLOCKED",
        "candidate_symbol": candidate.get("symbol"),
        "side": candidate.get("side"),
        "quantity": candidate.get("quantity"),
        "notional": candidate.get("notional"),
        "margin": candidate.get("margin"),
        "leverage_recommendation": candidate.get("leverage_recommendation"),
        "margin_mode_recommendation": candidate.get("margin_mode_recommendation"),
        "stop_exit_plan": {
            "stop_distance_bps": candidate.get("stop_distance_bps"),
            "dynamic_exit_required": True,
            "static_stop_final_output_allowed": False,
            "static_take_profit_final_output_allowed": False,
        },
        "max_loss": candidate.get("max_loss"),
        "liquidation_buffer": candidate.get("liquidation_buffer_bps"),
        "reduce_only_plan": {
            "reduce_only_required_for_closes": True,
            "candidate_reduce_only": _bool(_first_present(candidate_signal and candidate_signal.get("reduce_only"), False)),
            "close_only_capability_required": True,
        },
        "why_allowed": allowed_reasons,
        "why_not_allowed": blockers,
        "pre_submit_status": {
            "status": pre_submit.get("status"),
            "submit_allowed": pre_submit.get("submit_allowed"),
            "would_submit_if_operator_approved": pre_submit.get("would_submit_if_operator_approved"),
            "operator_review_ready": pre_submit.get("operator_review_ready"),
        },
        "no_live_mutation": True,
        **_safety_flags(),
    }


def build_real_trader_readiness_status(
    pre_submit_status: Mapping[str, Any],
    kill_switch_status: Mapping[str, Any],
    position_reconciliation_status: Mapping[str, Any],
    *,
    operator_truth: Mapping[str, Any] | None = None,
    generated_utc: str | None = None,
) -> dict[str, Any]:
    pre_submit = _as_dict(pre_submit_status)
    kill_switch = _as_dict(kill_switch_status)
    reconciliation = _as_dict(position_reconciliation_status)
    truth = _as_dict(operator_truth)
    blockers = list(_as_list(pre_submit.get("blockers")))
    if kill_switch.get("status") != "LIVE_KILL_SWITCH_CLEAR":
        blockers.extend(_as_list(kill_switch.get("blockers")) or ["KILL_SWITCH_NOT_CLEAR"])
    if reconciliation.get("reconciled") is not True:
        blockers.extend(_as_list(reconciliation.get("blockers")) or ["POSITION_RECONCILIATION_NOT_READY"])
    unique = list(dict.fromkeys(str(item) for item in blockers if str(item)))
    non_operator_blockers = [item for item in unique if item not in OPERATOR_GATE_BLOCKERS]
    ready_for_operator_review = not non_operator_blockers and pre_submit.get("operator_review_ready") is True
    live_submit_allowed = not unique and pre_submit.get("submit_allowed") is True
    checklist = {
        "read_only_signed_account_check": "SIGNED_ACCOUNT_READ_MISSING" not in unique,
        "available_margin_check": "AVAILABLE_MARGIN_BELOW_REQUIRED_INITIAL_MARGIN" not in unique
        and "AVAILABLE_MARGIN_MISSING" not in unique,
        "position_mode_check": "HEDGE_MODE_UNKNOWN" not in unique
        and "HEDGE_MODE_MISMATCH" not in unique
        and "POSITION_MODE_SNAPSHOT_STALE" not in unique
        and "POSITION_MODE_READ_MISSING" not in unique,
        "open_orders_check": "UNEXPECTED_OPEN_EXCHANGE_ORDERS" not in unique
        and "OPEN_ORDERS_SNAPSHOT_STALE" not in unique
        and "OPEN_ORDERS_READ_MISSING" not in unique,
        "current_positions_check": reconciliation.get("reconciled") is True,
        "symbol_filters_check": "SYMBOL_FILTERS_NOT_VERIFIED" not in unique and "SYMBOL_FILTERS_STALE" not in unique,
        "min_notional_check": "MIN_NOTIONAL_MISSING" not in unique
        and "CANDIDATE_NOTIONAL_BELOW_MIN_EXECUTABLE" not in unique
        and "SYMBOL_FILTERS_STALE" not in unique,
        "step_size_check": "STEP_SIZE_MISSING" not in unique and "SYMBOL_FILTERS_STALE" not in unique,
        "tick_size_check": "TICK_SIZE_MISSING" not in unique and "SYMBOL_FILTERS_STALE" not in unique,
        "reduce_only_capability": True,
        "close_only_capability": True,
        "kill_switch": kill_switch.get("status") == "LIVE_KILL_SWITCH_CLEAR",
        "per_symbol_exposure_cap": "PER_SYMBOL_EXPOSURE_CAP_EXCEEDED" not in unique,
        "total_exposure_cap": "TOTAL_EXPOSURE_CAP_EXCEEDED" not in unique,
        "drawdown_cap": "DRAWDOWN_CAP_EXCEEDED" not in unique,
        "live_pre_submit_allocator": "LIVE_PRE_SUBMIT_ALLOCATOR_NOT_ALLOWING_SIZE" not in unique,
        "live_pre_submit_risk_gate": "LIVE_GATE_NOT_ENABLED" not in unique and "OPERATOR_APPROVAL_REQUIRED" not in unique,
        "live_pre_submit_microstructure_trust_gate": True,
        "live_order_payload_preview": bool(pre_submit.get("candidate")),
    }
    return {
        "schema_version": f"{SCHEMA_VERSION}_readiness",
        "generated_utc": generated_utc or _utc_now(),
        "status": "REAL_TRADER_READY_FOR_OPERATOR_REVIEW"
        if ready_for_operator_review
        else "REAL_TRADER_READINESS_BLOCKED",
        "ready_for_operator_review": ready_for_operator_review,
        "live_submit_allowed": live_submit_allowed,
        "operator_approval_required": True,
        "operator_truth_live_gate": _first_present(truth.get("live_gate"), pre_submit.get("live_gate")),
        "operator_truth_live_order_submit_allowed": truth.get("live_order_submit_allowed"),
        "operator_truth_live_order_submit_blocker": truth.get("live_order_submit_blocker"),
        "checklist": checklist,
        "blockers": unique,
        "non_operator_blockers": non_operator_blockers,
        "dry_run_only": True,
        "no_live_mutation": True,
        **_safety_flags(),
    }


def build_phase7_status_bundle(
    *,
    runtime_payload: Mapping[str, Any] | None,
    operator_truth: Mapping[str, Any] | None = None,
    account_snapshot: Mapping[str, Any] | None = None,
    symbol_filter_snapshot: Mapping[str, Any] | None = None,
    allocation_payload: Mapping[str, Any] | None = None,
    candidate_signal: Mapping[str, Any] | None = None,
    generated_utc: str | None = None,
    now_ms: int | float | None = None,
) -> dict[str, dict[str, Any]]:
    generated = generated_utc or _utc_now()
    pre_submit = build_live_pre_submit_dry_run_status(
        runtime_payload,
        operator_truth=operator_truth,
        account_snapshot=account_snapshot,
        symbol_filter_snapshot=symbol_filter_snapshot,
        allocation_payload=allocation_payload,
        candidate_signal=candidate_signal,
        generated_utc=generated,
        now_ms=now_ms,
    )
    kill_switch = pre_submit["kill_switch_status"]
    position_reconciliation = pre_submit["position_reconciliation_status"]
    operator_packet = build_first_live_canary_operator_packet(
        pre_submit,
        allocation_payload=allocation_payload,
        candidate_signal=candidate_signal,
        generated_utc=generated,
    )
    readiness = build_real_trader_readiness_status(
        pre_submit,
        kill_switch,
        position_reconciliation,
        operator_truth=operator_truth,
        generated_utc=generated,
    )
    return {
        "real_trader_readiness_status": readiness,
        "live_pre_submit_dry_run_status": pre_submit,
        "first_live_canary_operator_packet": operator_packet,
        "live_kill_switch_status": kill_switch,
        "live_position_reconciliation_status": position_reconciliation,
    }
