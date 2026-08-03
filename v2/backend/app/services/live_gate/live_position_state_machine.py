"""Live canary safety primitives.

Pure validation helpers for Pass 3A. These functions do not call exchanges,
write Redis, mutate leverage, mutate margin mode, or submit orders.
"""
from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from v2.backend.app.services.market_state_integrity.trust import TRUST_SCHEMA_VERSION

OPEN_ACTIONS_LONG = {"long", "open_long", "buy", "long_open"}
OPEN_ACTIONS_SHORT = {"short", "open_short", "sell", "short_open"}
CLOSE_ACTIONS_LONG = {"close_long", "long_close", "sell_reduce"}
CLOSE_ACTIONS_SHORT = {"close_short", "short_close", "buy_reduce"}
BAD_TERMINAL_STATUSES = {"REJECTED", "CANCELED", "CANCELLED", "EXPIRED", "BLOCKED", "DENIED"}
LIVE_CANARY_DEFAULT_MAX_SIGNED_READ_AGE_MS = 5_000


@dataclass(frozen=True)
class LiveCanaryConfig:
    live_canary_enabled: bool = False
    max_open_positions: int = 1
    max_notional_usd: float = 10.0
    max_daily_orders: int = 3
    max_daily_loss_usd: float = 10.0
    allowed_symbols: tuple[str, ...] = ()
    allow_hedge_mode: bool = False
    allow_averaging_down: bool = False
    allow_direct_flip: bool = False
    require_reduce_only_for_closes: bool = True
    require_kill_switch_clear: bool = True
    require_human_operator_arm: bool = True
    require_strict_pipeline_trust: bool = True
    require_pass2a_trusted_decision: bool = True
    require_replay_snapshot: bool = True
    require_mtf_snapshot: bool = True
    allow_leverage_mutation: bool = False
    allow_margin_mode_mutation: bool = False
    max_signed_read_age_ms: int = LIVE_CANARY_DEFAULT_MAX_SIGNED_READ_AGE_MS
    quantity_tolerance: float = 1e-8
    expected_margin_mode: str = "cross"
    expected_hedge_mode: bool = False

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "LiveCanaryConfig":
        if not isinstance(value, Mapping):
            return cls()
        fields = cls.__dataclass_fields__  # type: ignore[attr-defined]
        kwargs: dict[str, Any] = {}
        for name in fields:
            if name not in value:
                continue
            raw = value[name]
            if name == "allowed_symbols":
                kwargs[name] = tuple(str(item).upper() for item in (raw or []) if str(item).strip())
            else:
                kwargs[name] = raw
        return cls(**kwargs)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_symbols"] = list(self.allowed_symbols)
        return payload


@dataclass(frozen=True)
class LiveCanaryResult:
    allowed: bool
    reason_code: str
    transition_type: str = "UNKNOWN"
    required_order_flags: dict[str, Any] = field(default_factory=dict)
    expected_position_after: dict[str, Any] = field(default_factory=dict)
    audit_fields: dict[str, Any] = field(default_factory=dict)
    blockers: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["blockers"] = list(self.blockers)
        return payload


def normalize_side(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in {"", "NONE", "NO_POSITION", "FLAT", "0"}:
        return "FLAT"
    if text in {"LONG", "BUY", "BOTH_LONG"}:
        return "LONG"
    if text in {"SHORT", "SELL", "BOTH_SHORT"}:
        return "SHORT"
    if text in {"PARTIALLY_FILLED_OPEN", "PARTIAL_OPEN"}:
        return "PARTIALLY_FILLED_OPEN"
    if text in {"PARTIALLY_FILLED_CLOSE", "PARTIAL_CLOSE"}:
        return "PARTIALLY_FILLED_CLOSE"
    return "UNKNOWN"


def numeric(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "allow", "allowed", "approved"}


def validate_position_transition(
    *,
    local_position: Mapping[str, Any] | None,
    exchange_position: Mapping[str, Any] | None,
    requested_action: str,
    symbol: str,
    quantity: float,
    notional_usd: float,
    reduce_only: bool,
    config: LiveCanaryConfig | None = None,
    open_positions_count: int = 0,
) -> LiveCanaryResult:
    cfg = config or LiveCanaryConfig()
    blockers: list[str] = []
    symbol_u = str(symbol or "").upper()
    action = str(requested_action or "").lower()
    local_side = normalize_side((local_position or {}).get("side"))
    exchange_side = normalize_side((exchange_position or {}).get("side"))
    local_qty = abs(numeric((local_position or {}).get("quantity")))
    exchange_qty = abs(numeric((exchange_position or {}).get("quantity")))

    if not symbol_u:
        blockers.append("SYMBOL_MISSING")
    elif cfg.allowed_symbols and symbol_u not in cfg.allowed_symbols:
        blockers.append("SYMBOL_NOT_ALLOWLISTED")
    if local_side == "UNKNOWN":
        blockers.append("UNKNOWN_LOCAL_POSITION_STATE")
    if exchange_side == "UNKNOWN":
        blockers.append("UNKNOWN_EXCHANGE_POSITION_STATE")
    if open_positions_count >= cfg.max_open_positions and local_side == "FLAT" and action in OPEN_ACTIONS_LONG | OPEN_ACTIONS_SHORT:
        blockers.append("MAX_OPEN_POSITIONS_EXCEEDED")
    if quantity <= 0:
        blockers.append("QUANTITY_NOT_POSITIVE")
    if notional_usd <= 0:
        blockers.append("NOTIONAL_NOT_POSITIVE")
    if notional_usd > cfg.max_notional_usd:
        blockers.append("MAX_NOTIONAL_EXCEEDED")

    transition = "UNKNOWN"
    expected_after = {"symbol": symbol_u, "side": local_side, "quantity": local_qty}
    required_flags: dict[str, Any] = {"reduce_only": False}

    if action in OPEN_ACTIONS_LONG:
        if local_side == "FLAT" and exchange_side in {"FLAT", "LONG"} and exchange_qty <= cfg.quantity_tolerance:
            transition = "FLAT_TO_LONG_OPEN"
            expected_after = {"symbol": symbol_u, "side": "LONG", "quantity": quantity}
        elif local_side == "LONG":
            transition = "LONG_ADD_EXPOSURE"
            if not cfg.allow_averaging_down:
                blockers.append("AVERAGING_DOWN_DISABLED")
        elif local_side == "SHORT":
            transition = "SHORT_TO_LONG_DIRECT_FLIP"
            if not cfg.allow_direct_flip:
                blockers.append("DIRECT_FLIP_BLOCKED")
        else:
            blockers.append("OPEN_LONG_INVALID_FROM_STATE")
    elif action in OPEN_ACTIONS_SHORT:
        if local_side == "FLAT" and exchange_side in {"FLAT", "SHORT"} and exchange_qty <= cfg.quantity_tolerance:
            transition = "FLAT_TO_SHORT_OPEN"
            expected_after = {"symbol": symbol_u, "side": "SHORT", "quantity": quantity}
        elif local_side == "SHORT":
            transition = "SHORT_ADD_EXPOSURE"
            if not cfg.allow_averaging_down:
                blockers.append("AVERAGING_DOWN_DISABLED")
        elif local_side == "LONG":
            transition = "LONG_TO_SHORT_DIRECT_FLIP"
            if not cfg.allow_direct_flip:
                blockers.append("DIRECT_FLIP_BLOCKED")
        else:
            blockers.append("OPEN_SHORT_INVALID_FROM_STATE")
    elif action in CLOSE_ACTIONS_LONG:
        transition = "LONG_TO_LONG_CLOSE"
        required_flags = {"reduce_only": True}
        expected_after = {"symbol": symbol_u, "side": "FLAT", "quantity": max(0.0, local_qty - quantity)}
        if local_side != "LONG":
            blockers.append("CLOSE_LONG_WITHOUT_LONG_POSITION")
        if cfg.require_reduce_only_for_closes and not reduce_only:
            blockers.append("REDUCE_ONLY_REQUIRED_FOR_CLOSE")
    elif action in CLOSE_ACTIONS_SHORT:
        transition = "SHORT_TO_SHORT_CLOSE"
        required_flags = {"reduce_only": True}
        expected_after = {"symbol": symbol_u, "side": "FLAT", "quantity": max(0.0, local_qty - quantity)}
        if local_side != "SHORT":
            blockers.append("CLOSE_SHORT_WITHOUT_SHORT_POSITION")
        if cfg.require_reduce_only_for_closes and not reduce_only:
            blockers.append("REDUCE_ONLY_REQUIRED_FOR_CLOSE")
    elif local_side in {"PARTIALLY_FILLED_OPEN", "PARTIALLY_FILLED_CLOSE"}:
        transition = f"{local_side}_RECONCILE_ONLY"
        blockers.append("PARTIAL_FILL_RECONCILIATION_REQUIRED")
    else:
        blockers.append("ACTION_NOT_SUPPORTED")

    allowed = not blockers
    return LiveCanaryResult(
        allowed=allowed,
        reason_code="ALLOW" if allowed else blockers[0],
        transition_type=transition,
        required_order_flags=required_flags,
        expected_position_after=expected_after,
        audit_fields={
            "symbol": symbol_u,
            "local_side": local_side,
            "exchange_side": exchange_side,
            "local_quantity": local_qty,
            "exchange_quantity": exchange_qty,
            "requested_action": action,
            "quantity": quantity,
            "notional_usd": notional_usd,
        },
        blockers=tuple(dict.fromkeys(blockers)),
    )


def reconcile_exchange_local_state(
    *,
    exchange_position: Mapping[str, Any] | None,
    local_position: Mapping[str, Any] | None,
    open_orders: list[Mapping[str, Any]] | None,
    hedge_mode: bool | None,
    margin_mode: str | None,
    signed_read_ts_ms: int | float | None,
    now_ms: int | float | None = None,
    config: LiveCanaryConfig | None = None,
) -> dict[str, Any]:
    cfg = config or LiveCanaryConfig()
    current_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    blockers: list[str] = []
    local_side = normalize_side((local_position or {}).get("side"))
    exchange_side = normalize_side((exchange_position or {}).get("side"))
    local_qty = abs(numeric((local_position or {}).get("quantity")))
    exchange_qty = abs(numeric((exchange_position or {}).get("quantity")))
    signed_age = None if signed_read_ts_ms is None else max(0, current_ms - int(signed_read_ts_ms))

    if signed_age is None:
        blockers.append("SIGNED_READ_TIMESTAMP_MISSING")
    elif signed_age > cfg.max_signed_read_age_ms:
        blockers.append("SIGNED_READ_STALE")
    if local_side == "UNKNOWN":
        blockers.append("UNKNOWN_LOCAL_POSITION_STATE")
    if exchange_side == "UNKNOWN":
        blockers.append("UNKNOWN_EXCHANGE_POSITION_STATE")
    if local_side != exchange_side:
        blockers.append("LOCAL_EXCHANGE_SIDE_MISMATCH")
    if abs(local_qty - exchange_qty) > cfg.quantity_tolerance:
        blockers.append("LOCAL_EXCHANGE_QUANTITY_MISMATCH")
    if open_orders:
        blockers.append("UNEXPECTED_OPEN_EXCHANGE_ORDERS")
    if hedge_mode is None:
        blockers.append("HEDGE_MODE_UNKNOWN")
    elif bool(hedge_mode) != cfg.expected_hedge_mode:
        blockers.append("HEDGE_MODE_MISMATCH")
    if bool(hedge_mode) and not cfg.allow_hedge_mode:
        blockers.append("HEDGE_MODE_DISABLED")
    normalized_margin = str(margin_mode or "").strip().lower()
    if not normalized_margin:
        blockers.append("MARGIN_MODE_UNKNOWN")
    elif normalized_margin != str(cfg.expected_margin_mode).lower():
        blockers.append("MARGIN_MODE_MISMATCH")

    return {
        "reconciled": not blockers,
        "exchange_position": dict(exchange_position or {}),
        "local_position": dict(local_position or {}),
        "open_orders": [dict(item) for item in (open_orders or [])],
        "mismatch_reason": blockers[0] if blockers else None,
        "blockers": list(dict.fromkeys(blockers)),
        "signed_read_age_ms": signed_age,
    }


def reconcile_order_lifecycle(
    *,
    local_position: Mapping[str, Any] | None,
    order_update: Mapping[str, Any],
) -> dict[str, Any]:
    status = str(order_update.get("status") or order_update.get("order_status") or "UNKNOWN").upper()
    filled_qty = abs(numeric(order_update.get("filled_quantity") or order_update.get("executed_qty")))
    original_qty = abs(numeric(order_update.get("quantity") or order_update.get("orig_qty")))
    remaining_qty = max(0.0, original_qty - filled_qty) if original_qty else numeric(order_update.get("remaining_quantity"), 0.0)
    avg_fill_price = numeric(order_update.get("avg_fill_price") or order_update.get("average_fill_price"), 0.0)
    fee = numeric(order_update.get("fee") or order_update.get("commission"), 0.0)
    position_before = dict(local_position or {})
    position_after = dict(position_before)
    update_position = False
    blocks_future = False
    training_positive_allowed = False
    reason = "ORDER_STATUS_UNKNOWN"

    if status == "FILLED":
        update_position = True
        training_positive_allowed = True
        reason = "FILLED_CONFIRMED"
        position_after.update(_position_after_fill(position_before, order_update, filled_qty))
    elif status == "PARTIALLY_FILLED":
        update_position = filled_qty > 0
        training_positive_allowed = False
        reason = "PARTIAL_FILL_REQUIRES_RECONCILIATION"
        blocks_future = True
        position_after.update(_position_after_fill(position_before, order_update, filled_qty))
    elif status in BAD_TERMINAL_STATUSES:
        reason = f"{status}_DOES_NOT_UPDATE_POSITION"
        blocks_future = False
        training_positive_allowed = False
    else:
        reason = "UNKNOWN_ORDER_STATUS_BLOCKS_SYMBOL"
        blocks_future = True
        training_positive_allowed = False

    return {
        "status": status,
        "update_local_position": update_position,
        "position_before": position_before,
        "position_after": position_after if update_position else position_before,
        "filled_quantity": filled_qty,
        "average_fill_price": avg_fill_price,
        "fee": fee,
        "remaining_quantity": remaining_qty,
        "blocks_future_orders_for_symbol": blocks_future,
        "positive_training_feedback_allowed": training_positive_allowed,
        "reason_code": reason,
    }


def _position_after_fill(position_before: Mapping[str, Any], order_update: Mapping[str, Any], filled_qty: float) -> dict[str, Any]:
    action = str(order_update.get("action") or order_update.get("side") or "").lower()
    side_before = normalize_side(position_before.get("side"))
    qty_before = abs(numeric(position_before.get("quantity")))
    if action in OPEN_ACTIONS_LONG:
        return {"side": "LONG", "quantity": qty_before + filled_qty}
    if action in OPEN_ACTIONS_SHORT:
        return {"side": "SHORT", "quantity": qty_before + filled_qty}
    if action in CLOSE_ACTIONS_LONG | CLOSE_ACTIONS_SHORT:
        remaining = max(0.0, qty_before - filled_qty)
        return {"side": "FLAT" if remaining <= 0 else side_before, "quantity": remaining}
    return {"side": side_before, "quantity": qty_before}


def can_create_positive_training_feedback(order_record: Mapping[str, Any]) -> bool:
    status = str(order_record.get("status") or order_record.get("order_status") or order_record.get("fill_status") or "").upper()
    if status in BAD_TERMINAL_STATUSES or status == "UNKNOWN":
        return False
    if status == "PARTIALLY_FILLED":
        return False
    return status == "FILLED"


def validate_canary_caps(
    *,
    config: LiveCanaryConfig,
    symbol: str,
    notional_usd: float,
    open_positions_count: int,
    daily_order_count: int,
    daily_loss_usd: float,
    kill_switch_active: bool,
    human_operator_armed: bool,
    leverage_mutation_attempt: bool = False,
    margin_mode_mutation_attempt: bool = False,
) -> dict[str, Any]:
    blockers: list[str] = []
    symbol_u = str(symbol or "").upper()
    if not config.live_canary_enabled:
        blockers.append("LIVE_CANARY_DISABLED")
    if config.allowed_symbols and symbol_u not in config.allowed_symbols:
        blockers.append("SYMBOL_NOT_ALLOWLISTED")
    if open_positions_count >= config.max_open_positions:
        blockers.append("MAX_OPEN_POSITIONS_EXCEEDED")
    if notional_usd > config.max_notional_usd:
        blockers.append("MAX_NOTIONAL_EXCEEDED")
    if daily_order_count >= config.max_daily_orders:
        blockers.append("MAX_DAILY_ORDERS_EXCEEDED")
    if daily_loss_usd >= config.max_daily_loss_usd:
        blockers.append("MAX_DAILY_LOSS_EXCEEDED")
    if config.require_kill_switch_clear and kill_switch_active:
        blockers.append("KILL_SWITCH_ACTIVE")
    if config.require_human_operator_arm and not human_operator_armed:
        blockers.append("HUMAN_OPERATOR_ARM_REQUIRED")
    if leverage_mutation_attempt and not config.allow_leverage_mutation:
        blockers.append("LEVERAGE_MUTATION_BLOCKED")
    if margin_mode_mutation_attempt and not config.allow_margin_mode_mutation:
        blockers.append("MARGIN_MODE_MUTATION_BLOCKED")
    return {"allowed": not blockers, "blockers": list(dict.fromkeys(blockers))}


def validate_trusted_decision_contract(
    decision: Mapping[str, Any] | None,
    *,
    replay_snapshot_exists: bool,
    mtf_snapshot_exists: bool,
) -> dict[str, Any]:
    blockers: list[str] = []
    record = decision or {}
    required = (
        "decision_id",
        "prediction_id",
        "mtf_snapshot_id",
        "replay_snapshot_id",
        "feature_cutoff",
        "available_at",
        "all_tf_candle_timestamps",
    )
    if record.get("trust_schema_version") != TRUST_SCHEMA_VERSION:
        blockers.append("TRUST_SCHEMA_MISSING")
    for field in required:
        value = record.get(field)
        if value in (None, "", [], {}):
            blockers.append(f"TRUST_FIELD_MISSING:{field}")
    if record.get("routes_to_live") is not False:
        blockers.append("ROUTES_TO_LIVE_NOT_FALSE")
    if record.get("live_order_allowed") is not False:
        blockers.append("LIVE_ORDER_ALLOWED_NOT_FALSE")
    if not replay_snapshot_exists:
        blockers.append("REPLAY_SNAPSHOT_MISSING")
    if not mtf_snapshot_exists:
        blockers.append("MTF_SNAPSHOT_MISSING")
    return {"allowed": not blockers, "blockers": list(dict.fromkeys(blockers))}


def evaluate_live_canary_preflight(
    *,
    config: LiveCanaryConfig | None = None,
    decision: Mapping[str, Any] | None,
    replay_snapshot_exists: bool,
    mtf_snapshot_exists: bool,
    strict_pipeline_trust_ok: bool,
    pass2a_trusted_decision_ok: bool,
    runtime_payload: Mapping[str, Any] | None,
    local_position: Mapping[str, Any] | None,
    exchange_position: Mapping[str, Any] | None,
    open_orders: list[Mapping[str, Any]] | None,
    hedge_mode: bool | None,
    margin_mode: str | None,
    signed_read_ts_ms: int | float | None,
    requested_action: str,
    symbol: str,
    quantity: float,
    notional_usd: float,
    reduce_only: bool,
    open_positions_count: int = 0,
    daily_order_count: int = 0,
    daily_loss_usd: float = 0.0,
    kill_switch_active: bool = False,
    human_operator_armed: bool = False,
    lifecycle_status: Mapping[str, Any] | None = None,
    leverage_mutation_attempt: bool = False,
    margin_mode_mutation_attempt: bool = False,
    now_ms: int | float | None = None,
) -> dict[str, Any]:
    cfg = config or LiveCanaryConfig()
    blockers: list[str] = []
    runtime = runtime_payload or {}

    if cfg.require_strict_pipeline_trust and not strict_pipeline_trust_ok:
        blockers.append("STRICT_PIPELINE_TRUST_NOT_PASSING")
    if cfg.require_pass2a_trusted_decision and not pass2a_trusted_decision_ok:
        blockers.append("PASS2A_TRUSTED_DECISION_MISSING")
    if str(runtime.get("release_mode") or "NON_LIVE").upper() != "LIVE_CANARY_APPROVED":
        blockers.append("RELEASE_MODE_NON_LIVE")
    if runtime.get("order_transport_submit_enabled") is not True:
        blockers.append("ORDER_TRANSPORT_SUBMIT_DISABLED")
    if runtime.get("live_trading_enabled") is not True:
        blockers.append("LIVE_TRADING_DISABLED")
    if runtime.get("places_real_order") is True:
        blockers.append("RUNTIME_ALREADY_MARKS_REAL_ORDER")
    if runtime.get("exchange_action_taken") is True:
        blockers.append("RUNTIME_EXCHANGE_ACTION_ALREADY_TAKEN")

    trust = validate_trusted_decision_contract(
        decision,
        replay_snapshot_exists=replay_snapshot_exists,
        mtf_snapshot_exists=mtf_snapshot_exists,
    )
    blockers.extend(trust["blockers"])
    caps = validate_canary_caps(
        config=cfg,
        symbol=symbol,
        notional_usd=notional_usd,
        open_positions_count=open_positions_count,
        daily_order_count=daily_order_count,
        daily_loss_usd=daily_loss_usd,
        kill_switch_active=kill_switch_active,
        human_operator_armed=human_operator_armed,
        leverage_mutation_attempt=leverage_mutation_attempt,
        margin_mode_mutation_attempt=margin_mode_mutation_attempt,
    )
    blockers.extend(caps["blockers"])
    transition = validate_position_transition(
        local_position=local_position,
        exchange_position=exchange_position,
        requested_action=requested_action,
        symbol=symbol,
        quantity=quantity,
        notional_usd=notional_usd,
        reduce_only=reduce_only,
        config=cfg,
        open_positions_count=open_positions_count,
    )
    blockers.extend(transition.blockers)
    reconciliation = reconcile_exchange_local_state(
        exchange_position=exchange_position,
        local_position=local_position,
        open_orders=open_orders,
        hedge_mode=hedge_mode,
        margin_mode=margin_mode,
        signed_read_ts_ms=signed_read_ts_ms,
        now_ms=now_ms,
        config=cfg,
    )
    blockers.extend(reconciliation["blockers"])
    lifecycle = dict(lifecycle_status or {"status": "READY"})
    if lifecycle.get("blocks_future_orders_for_symbol") is True:
        blockers.append("ORDER_LIFECYCLE_BLOCKS_SYMBOL")
    if lifecycle.get("status") in {"UNKNOWN", "PARTIALLY_FILLED"}:
        blockers.append("ORDER_LIFECYCLE_RECONCILIATION_REQUIRED")

    unique_blockers = tuple(dict.fromkeys(str(item) for item in blockers if str(item)))
    return {
        "submit_allowed": not unique_blockers,
        "reason_code": "ALLOW" if not unique_blockers else unique_blockers[0],
        "blockers": list(unique_blockers),
        "live_canary_enabled": cfg.live_canary_enabled,
        "config": cfg.to_dict(),
        "trust_contract": trust,
        "canary_caps": caps,
        "state_machine": transition.to_dict(),
        "exchange_local_reconciliation": reconciliation,
        "order_lifecycle": lifecycle,
        "audit_payload": {
            "symbol": str(symbol or "").upper(),
            "requested_action": requested_action,
            "quantity": quantity,
            "notional_usd": notional_usd,
            "strict_pipeline_trust_ok": strict_pipeline_trust_ok,
            "pass2a_trusted_decision_ok": pass2a_trusted_decision_ok,
            "replay_snapshot_exists": replay_snapshot_exists,
            "mtf_snapshot_exists": mtf_snapshot_exists,
        },
    }
