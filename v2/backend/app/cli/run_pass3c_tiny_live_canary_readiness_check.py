"""Pass 3C tiny live-canary readiness check.

Read-only operator planning command. It does not arm live trading, submit
orders, write approval tokens, change leverage, change margin mode, cancel
orders, or mutate exchange state.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from app.cli.run_pass3b_exact_live_path_dry_run import build_signed_read_context, numeric, parse_env, redact, read_live_control_state, read_json_key, signed_get, utc_now
from app.services.live_gate.live_position_state_machine import LiveCanaryConfig, evaluate_live_canary_preflight
from app.services.market_state_integrity.trust import TRUST_SCHEMA_VERSION

STATUS_BLOCKED_INSUFFICIENT_BALANCE = "PASS3C_BLOCKED_INSUFFICIENT_BALANCE"
STATUS_BLOCKED_EDGE_INSUFFICIENT_SAMPLE = "PASS3C_BLOCKED_EDGE_INSUFFICIENT_SAMPLE"
STATUS_BLOCKED_LIVE_CONTROL_NOT_ARMED = "PASS3C_BLOCKED_LIVE_CONTROL_NOT_ARMED"
STATUS_BLOCKED_KILL_SWITCH = "PASS3C_BLOCKED_KILL_SWITCH"
STATUS_BLOCKED_RECONCILIATION = "PASS3C_BLOCKED_RECONCILIATION"
STATUS_BLOCKED_STRICT_TRUST = "PASS3C_BLOCKED_STRICT_TRUST"
STATUS_BLOCKED_OPEN_POSITION = "PASS3C_BLOCKED_OPEN_POSITION"
STATUS_BLOCKED_OPEN_ORDER = "PASS3C_BLOCKED_OPEN_ORDER"
STATUS_BLOCKED_CANDIDATE_NOTIONAL = "PASS3C_BLOCKED_CANDIDATE_NOTIONAL"
STATUS_READY = "PASS3C_READY_FOR_OPERATOR_REVIEW"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_pass3c_tiny_live_canary_readiness_check")
    parser.add_argument("--redis-url", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--symbol", default="")
    parser.add_argument("--quantity", type=float, default=0.001)
    parser.add_argument("--notional-usd", type=float, default=5.0)
    parser.add_argument("--execution-validation-canary-acknowledged", action="store_true")
    args = parser.parse_args(argv)

    client = redis_client(args.redis_url)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output_dir) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    report = run_readiness_check(
        client=client,
        redis_url=args.redis_url,
        output_dir=out_dir,
        run_id=run_id,
        symbol=args.symbol,
        quantity=args.quantity,
        notional_usd=args.notional_usd,
        execution_validation_canary_acknowledged=args.execution_validation_canary_acknowledged,
    )
    (out_dir / "pass3c_tiny_live_canary_readiness_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    (out_dir / f"PASS3C_TINY_LIVE_CANARY_ACTIVATION_PLAN_{run_id}.md").write_text(
        render_markdown(report),
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


def redis_client(redis_url: str) -> Any:
    import redis  # type: ignore[import-not-found]

    return redis.Redis.from_url(redis_url, decode_responses=True)


def run_readiness_check(
    *,
    client: Any,
    redis_url: str,
    output_dir: Path,
    run_id: str,
    symbol: str = "BTCUSDT",
    quantity: float = 0.001,
    notional_usd: float = 5.0,
    execution_validation_canary_acknowledged: bool = False,
) -> dict[str, Any]:
    symbol_u = str(symbol or "BTCUSDT").upper()
    live_state = read_live_control_state(client)
    live_gate = live_state.get("live_gate_state") if isinstance(live_state.get("live_gate_state"), Mapping) else {}
    trader_state = live_state.get("trader_execution_state") if isinstance(live_state.get("trader_execution_state"), Mapping) else {}
    transport_state = live_state.get("live_order_transport_status") if isinstance(live_state.get("live_order_transport_status"), Mapping) else {}
    strict = latest_report_summary(("pipeline_trust_evidence_pass3c", "pipeline_trust_evidence_pass3b", "pipeline_trust_evidence_pass3a"))
    recorded = latest_recorded_summary(("recorded_state_verification_pass3c", "recorded_state_verification_pass3b", "recorded_state_verification_pass3a"))
    pass2b = latest_pass2b_summary()
    trust = trusted_evidence_summary(client)
    signed_reads = build_signed_read_context(symbol_u)
    signed_available = signed_reads.get("available") is True
    exchange_position = signed_reads.get("exchange_position") if isinstance(signed_reads.get("exchange_position"), Mapping) else {}
    open_orders = [item for item in signed_reads.get("open_orders", []) if isinstance(item, Mapping)] if signed_available else []
    filters = signed_reads.get("symbol_filter_status") if isinstance(signed_reads.get("symbol_filter_status"), Mapping) else {}
    account = signed_reads.get("account_margin_status") if isinstance(signed_reads.get("account_margin_status"), Mapping) else {}
    available_balance = numeric(account.get("_available_balance_usdt"), 0.0) if signed_available else 0.0
    min_notional = numeric(filters.get("min_notional"), 0.0)
    mark_price = build_mark_price_context(symbol_u)
    live_canary_config = LiveCanaryConfig.from_mapping(live_gate.get("live_canary_config") or live_gate.get("live_canary") or {})
    notional_validation = validate_candidate_notional(
        quantity=quantity,
        candidate_notional_usd=notional_usd,
        mark_price_context=mark_price,
        symbol_filter_status=filters,
        canary_config=live_canary_config,
    )
    required_balance = max(
        numeric(notional_validation.get("computed_notional_usd"), 0.0),
        notional_usd,
        min_notional,
    )
    accepted_symbols = [str(item).upper() for item in live_gate.get("accepted_live_symbols") or live_gate.get("live_symbols") or []]
    allowed_symbols = list(live_canary_config.allowed_symbols or tuple(accepted_symbols))
    candidate = candidate_record(symbol_u, quantity, notional_usd)
    runtime_payload = readiness_runtime_payload(live_gate, allowed_symbols)
    preflight = evaluate_live_canary_preflight(
        config=live_canary_config if live_canary_config.allowed_symbols else LiveCanaryConfig.from_mapping(live_canary_config.to_dict() | {"allowed_symbols": allowed_symbols}),
        decision=candidate,
        replay_snapshot_exists=trust["replay_snapshot_count"] > 0,
        mtf_snapshot_exists=trust["mtf_snapshot_count"] > 0,
        strict_pipeline_trust_ok=(strict.get("critical_failures") == 0),
        pass2a_trusted_decision_ok=trust["trusted_prediction_count"] > 0,
        runtime_payload=runtime_payload,
        local_position=local_position_from_state(trader_state, live_gate, symbol_u),
        exchange_position=exchange_position,
        open_orders=open_orders,
        hedge_mode=(signed_reads.get("position_mode_status") or {}).get("dual_side_position") if isinstance(signed_reads.get("position_mode_status"), Mapping) else None,
        margin_mode=str(signed_reads.get("margin_mode") or ""),
        signed_read_ts_ms=numeric(signed_reads.get("signed_read_ts_ms"), 0.0) or None,
        requested_action="long",
        symbol=symbol_u,
        quantity=quantity,
        notional_usd=notional_usd,
        reduce_only=False,
        open_positions_count=int(numeric(live_gate.get("open_positions_count"), 0.0)),
        daily_order_count=int(numeric(live_gate.get("daily_order_count"), 0.0)),
        daily_loss_usd=numeric(live_gate.get("daily_loss_usd"), 0.0),
        kill_switch_active=live_gate.get("kill_switch_active") is True,
        human_operator_armed=live_gate.get("live_canary_human_armed") is True,
        lifecycle_status=live_gate.get("order_lifecycle_status") if isinstance(live_gate.get("order_lifecycle_status"), Mapping) else {"status": "READY"},
        leverage_mutation_attempt=live_gate.get("leverage_mutation_requested") is True,
        margin_mode_mutation_attempt=live_gate.get("margin_mode_mutation_requested") is True,
    )
    blockers = classify_blockers(
        strict=strict,
        recorded=recorded,
        trust=trust,
        pass2b=pass2b,
        execution_validation_canary_acknowledged=execution_validation_canary_acknowledged,
        signed_available=signed_available,
        preflight=preflight,
        live_gate=live_gate,
        transport_state=transport_state,
        exchange_position=exchange_position,
        open_orders=open_orders,
        available_balance=available_balance,
        required_balance=required_balance,
        notional_validation=notional_validation,
        allowed_symbols=allowed_symbols,
        symbol=symbol_u,
    )
    status = choose_status(blockers)
    return {
        "run_id": run_id,
        "generated_at": utc_now(),
        "output_dir": str(output_dir),
        "redis_url": redact(redis_url),
        "status": status,
        "pass_status": {
            "pass1a_live_submit_disarmed": True,
            "pass2a_trusted_prediction_replay_mtf": trust["trusted_prediction_count"] > 0 and trust["replay_snapshot_count"] > 0 and trust["mtf_snapshot_count"] > 0,
            "pass2b_edge_framework": True,
            "pass2b_verdict": pass2b.get("verdict") or "UNKNOWN",
            "pass3a_live_canary_safety": True,
            "pass3b_exact_live_path": "PASS3B_BLOCKED_INSUFFICIENT_AVAILABLE_BALANCE",
        },
        "execution_validation_canary_acknowledged": execution_validation_canary_acknowledged,
        "canary_intent": "EXECUTION_PATH_VALIDATION_ONLY",
        "not_strategy_profitability_launch": True,
        "strict_status": strict,
        "recorded_state_status": recorded,
        "trusted_evidence": trust,
        "pass2b_summary": pass2b,
        "live_control_state": summarize_live_control(live_gate, transport_state),
        "candidate": {"symbol": symbol_u, "side": "BUY", "action": "long", "quantity": quantity, "notional_usd": notional_usd, "order_type": "MARKET", "reduce_only": False},
        "futures_balance": {
            "signed_read_available": signed_available,
            "available_balance_usdt": round(available_balance, 8),
            "minimum_required_usdt": round(required_balance, 8),
            "min_notional_usdt": round(min_notional, 8),
            "insufficient": available_balance < required_balance,
        },
        "notional_validation": notional_validation,
        "canary_config": {
            "live_canary_enabled": live_canary_config.live_canary_enabled,
            "max_notional_usd": live_canary_config.max_notional_usd,
            "max_daily_orders": live_canary_config.max_daily_orders,
            "max_daily_loss_usd": live_canary_config.max_daily_loss_usd,
            "max_open_positions": live_canary_config.max_open_positions,
            "allowed_symbols": allowed_symbols,
            "allow_leverage_mutation": live_canary_config.allow_leverage_mutation,
            "allow_margin_mode_mutation": live_canary_config.allow_margin_mode_mutation,
        },
        "kill_switch_status": {"active": live_gate.get("kill_switch_active") is True, "enabled": live_gate.get("kill_switch_enabled")},
        "human_operator_arm_status": {"armed": live_gate.get("live_canary_human_armed") is True, "operator_approved": live_gate.get("operator_approved") is True},
        "exchange_local_reconciliation": preflight.get("exchange_local_reconciliation"),
        "state_machine": preflight.get("state_machine"),
        "canary_caps": preflight.get("canary_caps"),
        "readiness_preflight": preflight,
        "blockers": blockers,
        "go_conditions": go_conditions(),
        "no_go_conditions": no_go_conditions(),
        "required_human_acknowledgements": required_human_acknowledgements(),
        "activation_sequence_not_run": activation_sequence(),
        "rollback_disarm_checklist": rollback_disarm_checklist(),
        "submit_allowed": False,
        "live_order_submitted": False,
        "places_real_order": False,
        "exchange_action_taken": False,
        "leverage_changed": False,
        "margin_mode_changed": False,
        "read_only": True,
    }


def candidate_record(symbol: str, quantity: float, notional_usd: float) -> dict[str, Any]:
    return {
        "trust_schema_version": TRUST_SCHEMA_VERSION,
        "decision_id": "pass3c_operator_plan_candidate",
        "prediction_id": "pass3c_operator_plan_candidate",
        "mtf_snapshot_id": "pass3c_requires_existing_mtf_snapshot",
        "replay_snapshot_id": "pass3c_requires_existing_replay_snapshot",
        "feature_cutoff": "pass3c_plan_not_model_output",
        "available_at": "pass3c_plan_not_model_output",
        "all_tf_candle_timestamps": [1, 2, 3, 4, 5],
        "routes_to_live": False,
        "live_order_allowed": False,
        "symbol": symbol,
        "action": "long",
        "selected_action": "long",
        "quantity": quantity,
        "requested_notional_usdt": notional_usd,
    }


def build_mark_price_context(symbol: str) -> dict[str, Any]:
    env = parse_env(Path("v2/.env.local"))
    api_key = env.get("BINANCE_API_KEY") or env.get("BINANCE_FUT_API_KEY")
    api_secret = env.get("BINANCE_API_SECRET") or env.get("BINANCE_SECRET_KEY") or env.get("BINANCE_FUT_API_SECRET")
    if not api_key or not api_secret:
        return {"available": False, "reason": "SIGNED_MARK_PRICE_MISSING"}
    base = os.environ.get("V2_BINANCE_USDM_BASE_URL", "https://fapi.binance.com").rstrip("/")
    now_ms = int(time.time() * 1000)
    try:
        payload = signed_get(base, "/fapi/v2/positionRisk", {"symbol": symbol}, api_key, api_secret)
    except Exception as exc:
        return {"available": False, "reason": type(exc).__name__}
    row = payload[0] if isinstance(payload, list) and payload and isinstance(payload[0], Mapping) else payload if isinstance(payload, Mapping) else {}
    mark_price = numeric(row.get("markPrice"), 0.0)
    if mark_price <= 0:
        return {"available": False, "reason": "SIGNED_MARK_PRICE_MISSING", "source": "GET /fapi/v2/positionRisk"}
    return {
        "available": True,
        "symbol": symbol,
        "signed_mark_price": mark_price,
        "signed_mark_price_ts_ms": now_ms,
        "source": "GET /fapi/v2/positionRisk",
    }


def validate_candidate_notional(
    *,
    quantity: float,
    candidate_notional_usd: float,
    mark_price_context: Mapping[str, Any],
    symbol_filter_status: Mapping[str, Any],
    canary_config: LiveCanaryConfig,
    now_ms: int | None = None,
    tolerance_pct: float = 0.001,
) -> dict[str, Any]:
    current_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    blockers: list[str] = []
    mark_price = numeric(mark_price_context.get("signed_mark_price"), 0.0)
    mark_ts = numeric(mark_price_context.get("signed_mark_price_ts_ms"), 0.0)
    mark_age = None if mark_ts <= 0 else max(0, current_ms - int(mark_ts))
    min_qty = numeric(symbol_filter_status.get("min_qty"), 0.0)
    step_size = numeric(symbol_filter_status.get("step_size"), 0.0)
    min_notional = numeric(symbol_filter_status.get("min_notional"), 0.0)
    computed_notional = quantity * mark_price if mark_price > 0 else 0.0
    tolerance = max(0.01, abs(candidate_notional_usd) * tolerance_pct)

    if mark_price_context.get("available") is not True or mark_price <= 0:
        blockers.append("SIGNED_MARK_PRICE_MISSING")
    if mark_age is None:
        blockers.append("SIGNED_MARK_PRICE_MISSING")
    elif mark_age > canary_config.max_signed_read_age_ms:
        blockers.append("SIGNED_MARK_PRICE_STALE")
    if mark_price > 0 and abs(computed_notional - candidate_notional_usd) > tolerance:
        blockers.append("CANDIDATE_NOTIONAL_MARK_PRICE_MISMATCH")
    if min_qty > 0 and quantity < min_qty:
        blockers.append("QUANTITY_BELOW_MIN_QTY")
    if step_size > 0 and not quantity_matches_step_size(quantity, step_size):
        blockers.append("QUANTITY_STEP_SIZE_VIOLATION")
    if min_notional > 0 and computed_notional > 0 and computed_notional < min_notional:
        blockers.append("NOTIONAL_BELOW_EXCHANGE_MIN_NOTIONAL")
    if computed_notional > canary_config.max_notional_usd:
        blockers.append("NOTIONAL_ABOVE_CANARY_CAP")

    return {
        "valid": not blockers,
        "blockers": list(dict.fromkeys(blockers)),
        "signed_mark_price": round(mark_price, 8),
        "signed_mark_price_ts_ms": int(mark_ts) if mark_ts else None,
        "signed_mark_price_age_ms": mark_age,
        "computed_notional_usd": round(computed_notional, 8),
        "candidate_notional_usd": round(candidate_notional_usd, 8),
        "quantity": quantity,
        "min_quantity": min_qty,
        "step_size": step_size,
        "min_notional_usd": min_notional,
        "canary_max_notional_usd": canary_config.max_notional_usd,
        "tolerance_usd": round(tolerance, 8),
        "source": mark_price_context.get("source"),
    }


def quantity_matches_step_size(quantity: float, step_size: float) -> bool:
    try:
        qty = Decimal(str(quantity))
        step = Decimal(str(step_size))
    except Exception:
        return False
    if step <= 0:
        return True
    return qty.remainder_near(step) == 0


def readiness_runtime_payload(live_gate: Mapping[str, Any], allowed_symbols: list[str]) -> dict[str, Any]:
    payload = dict(live_gate or {})
    canary = dict(payload.get("live_canary_config") or payload.get("live_canary") or {})
    if allowed_symbols and not canary.get("allowed_symbols"):
        canary["allowed_symbols"] = allowed_symbols
    payload["live_canary_config"] = canary
    return payload


def local_position_from_state(trader_state: Mapping[str, Any], live_gate: Mapping[str, Any], symbol: str) -> dict[str, Any]:
    for source in (trader_state.get("local_position"), live_gate.get("local_position"), live_gate.get("current_position")):
        if isinstance(source, Mapping):
            return dict(source)
    return {"symbol": symbol, "side": "FLAT", "quantity": 0.0}


def trusted_evidence_summary(client: Any) -> dict[str, Any]:
    predictions = []
    try:
        keys = sorted(client.scan_iter(match="v2:prediction:*", count=500))
    except Exception:
        keys = []
    for key in keys:
        payload = read_json_key(client, str(key))
        if payload.get("trust_schema_version") == TRUST_SCHEMA_VERSION:
            predictions.append(payload)
    replay_count = count_pattern(client, "v2:replay:snapshots:*")
    mtf_count = count_pattern(client, "v2:market:mtf_snapshot:*") + count_pattern(client, "v2:decision:mtf_snapshot:*") + count_pattern(client, "v2:mtf_snapshot:*")
    linked = [
        row for row in predictions
        if row.get("replay_snapshot_id") and row.get("mtf_snapshot_id") and row.get("decision_id") and row.get("prediction_id")
    ]
    return {
        "trusted_prediction_count": len(predictions),
        "trusted_linked_prediction_count": len(linked),
        "replay_snapshot_count": replay_count,
        "mtf_snapshot_count": mtf_count,
        "missing_replay_or_mtf": not (linked and replay_count > 0 and mtf_count > 0),
    }


def classify_blockers(
    *,
    strict: Mapping[str, Any],
    recorded: Mapping[str, Any],
    trust: Mapping[str, Any],
    pass2b: Mapping[str, Any],
    execution_validation_canary_acknowledged: bool,
    signed_available: bool,
    preflight: Mapping[str, Any],
    live_gate: Mapping[str, Any],
    transport_state: Mapping[str, Any],
    exchange_position: Mapping[str, Any],
    open_orders: list[Mapping[str, Any]],
    available_balance: float,
    required_balance: float,
    notional_validation: Mapping[str, Any],
    allowed_symbols: list[str],
    symbol: str,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if int(strict.get("critical_failures") or 0) != 0:
        blockers.append(blocker(STATUS_BLOCKED_STRICT_TRUST, "STRICT_VERIFIER_FAILED"))
    if int(recorded.get("critical_failures") or 0) != 0:
        blockers.append(blocker(STATUS_BLOCKED_STRICT_TRUST, "RECORDED_STATE_VERIFIER_FAILED"))
    if int(strict.get("active_stale_count") or 0) > 0:
        blockers.append(blocker(STATUS_BLOCKED_STRICT_TRUST, "ACTIVE_STALE_PRESENT"))
    if trust.get("missing_replay_or_mtf") is True:
        blockers.append(blocker(STATUS_BLOCKED_STRICT_TRUST, "TRUSTED_REPLAY_OR_MTF_EVIDENCE_MISSING"))
    if not signed_available:
        blockers.append(blocker(STATUS_BLOCKED_RECONCILIATION, "SIGNED_READ_UNAVAILABLE"))
    reconciliation = preflight.get("exchange_local_reconciliation") if isinstance(preflight.get("exchange_local_reconciliation"), Mapping) else {}
    if reconciliation.get("reconciled") is False:
        blockers.append(blocker(STATUS_BLOCKED_RECONCILIATION, reconciliation.get("mismatch_reason") or "EXCHANGE_LOCAL_RECONCILIATION_FAILED"))
    if position_is_open(exchange_position):
        blockers.append(blocker(STATUS_BLOCKED_OPEN_POSITION, "EXISTING_OPEN_POSITION"))
    if open_orders:
        blockers.append(blocker(STATUS_BLOCKED_OPEN_ORDER, "UNEXPECTED_OPEN_ORDER"))
    if live_gate.get("kill_switch_active") is True:
        blockers.append(blocker(STATUS_BLOCKED_KILL_SWITCH, "KILL_SWITCH_ACTIVE"))
    if pass2b.get("verdict") != "EDGE_POSITIVE" and not execution_validation_canary_acknowledged:
        blockers.append(blocker(STATUS_BLOCKED_EDGE_INSUFFICIENT_SAMPLE, "PASS2B_EDGE_INSUFFICIENT_SAMPLE_ACK_REQUIRED"))
    for reason in notional_validation.get("blockers") or []:
        blockers.append(blocker(STATUS_BLOCKED_CANDIDATE_NOTIONAL, reason))
    if available_balance < required_balance:
        blockers.append(blocker(STATUS_BLOCKED_INSUFFICIENT_BALANCE, "INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER"))
    if allowed_symbols and symbol not in allowed_symbols:
        blockers.append(blocker(STATUS_BLOCKED_LIVE_CONTROL_NOT_ARMED, "SYMBOL_NOT_ALLOWLISTED"))
    if live_gate.get("live_canary_human_armed") is not True:
        blockers.append(blocker(STATUS_BLOCKED_LIVE_CONTROL_NOT_ARMED, "HUMAN_OPERATOR_ARM_REQUIRED"))
    if live_gate.get("release_mode") != "LIVE_CANARY_APPROVED":
        blockers.append(blocker(STATUS_BLOCKED_LIVE_CONTROL_NOT_ARMED, "RELEASE_MODE_NOT_LIVE_CANARY_APPROVED"))
    if live_gate.get("order_transport_submit_enabled") is not True:
        blockers.append(blocker(STATUS_BLOCKED_LIVE_CONTROL_NOT_ARMED, "ORDER_TRANSPORT_SUBMIT_DISABLED"))
    if live_gate.get("live_trading_enabled") is not True:
        blockers.append(blocker(STATUS_BLOCKED_LIVE_CONTROL_NOT_ARMED, "LIVE_TRADING_DISABLED"))
    canary_cfg = live_gate.get("live_canary_config") if isinstance(live_gate.get("live_canary_config"), Mapping) else {}
    if canary_cfg.get("live_canary_enabled") is not True:
        blockers.append(blocker(STATUS_BLOCKED_LIVE_CONTROL_NOT_ARMED, "LIVE_CANARY_DISABLED"))
    if live_gate.get("leverage_mutation_requested") is True or live_gate.get("leverage_mutation_allowed") is True:
        blockers.append(blocker(STATUS_BLOCKED_LIVE_CONTROL_NOT_ARMED, "LEVERAGE_MUTATION_NOT_ALLOWED_FOR_CANARY"))
    if live_gate.get("margin_mode_mutation_requested") is True or live_gate.get("margin_mutation_allowed") is True:
        blockers.append(blocker(STATUS_BLOCKED_LIVE_CONTROL_NOT_ARMED, "MARGIN_MODE_MUTATION_NOT_ALLOWED_FOR_CANARY"))
    if transport_state.get("order_submitted") is True or transport_state.get("writes_exchange_orders") is True:
        blockers.append(blocker(STATUS_BLOCKED_LIVE_CONTROL_NOT_ARMED, "TRANSPORT_ALREADY_MARKS_EXCHANGE_ACTION"))
    return dedupe_blockers(blockers)


def choose_status(blockers: list[dict[str, Any]]) -> str:
    priority = (
        STATUS_BLOCKED_STRICT_TRUST,
        STATUS_BLOCKED_RECONCILIATION,
        STATUS_BLOCKED_OPEN_POSITION,
        STATUS_BLOCKED_OPEN_ORDER,
        STATUS_BLOCKED_KILL_SWITCH,
        STATUS_BLOCKED_EDGE_INSUFFICIENT_SAMPLE,
        STATUS_BLOCKED_CANDIDATE_NOTIONAL,
        STATUS_BLOCKED_INSUFFICIENT_BALANCE,
        STATUS_BLOCKED_LIVE_CONTROL_NOT_ARMED,
    )
    statuses = {item.get("status") for item in blockers}
    for status in priority:
        if status in statuses:
            return status
    return STATUS_READY


def blocker(status: str, reason: Any) -> dict[str, str]:
    return {"status": status, "reason": str(reason)}


def dedupe_blockers(blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    out = []
    for item in blockers:
        key = (str(item.get("status")), str(item.get("reason")))
        if key in seen:
            continue
        seen.add(key)
        out.append({"status": key[0], "reason": key[1]})
    return out


def position_is_open(position: Mapping[str, Any]) -> bool:
    return str(position.get("side") or "FLAT").upper() not in {"", "FLAT", "NONE"} or numeric(position.get("quantity"), 0.0) > 0


def count_pattern(client: Any, pattern: str) -> int:
    try:
        return len(list(client.scan_iter(match=pattern, count=500)))
    except Exception:
        return 0


def latest_report_summary(roots: tuple[str, ...]) -> dict[str, Any]:
    reports: list[Path] = []
    for root in roots:
        reports.extend(Path(root).glob("*/report/pipeline_trust_report.json"))
    if not reports:
        return {"critical_failures": 1, "status": "not_available"}
    latest = sorted(reports)[-1]
    try:
        summary = dict((json.loads(latest.read_text(encoding="utf-8")).get("summary") or {}))
    except Exception:
        return {"critical_failures": 1, "status": "parse_failed", "_report_path": str(latest)}
    summary["_report_path"] = str(latest)
    summary["_evidence_run"] = str(latest.parents[1])
    return summary


def latest_recorded_summary(roots: tuple[str, ...]) -> dict[str, Any]:
    reports: list[Path] = []
    for root in roots:
        reports.extend(Path(root).glob("*/recorded_state_verification_report.json"))
    if not reports:
        return {"critical_failures": 1, "status": "not_available"}
    latest = sorted(reports)[-1]
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
    except Exception:
        return {"critical_failures": 1, "status": "parse_failed", "_report_path": str(latest)}
    summary = dict(payload.get("metrics") or payload.get("summary") or {})
    summary["_report_path"] = str(latest)
    summary["_recorded_run"] = str(latest.parent)
    return summary


def latest_pass2b_summary() -> dict[str, Any]:
    reports = sorted(Path(".").glob("pass2b*/**/pass2b_edge_proof.json"))
    if not reports:
        return {"verdict": "INSUFFICIENT_SAMPLE", "status": "not_available"}
    latest = reports[-1]
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
    except Exception:
        return {"verdict": "INSUFFICIENT_SAMPLE", "status": "parse_failed", "_report_path": str(latest)}
    return {
        "verdict": payload.get("verdict") or "UNKNOWN",
        "total_trusted_predictions": payload.get("total_trusted_predictions"),
        "actionable_predictions": payload.get("actionable_predictions"),
        "closed_paper_trades": payload.get("closed_paper_trades"),
        "invalid_feedback_count": payload.get("invalid_feedback_count"),
        "_report_path": str(latest),
    }


def summarize_live_control(live_gate: Mapping[str, Any], transport: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "live_gate": live_gate.get("live_gate"),
        "release_mode": live_gate.get("release_mode"),
        "live_canary_enabled": (live_gate.get("live_canary_config") or {}).get("live_canary_enabled") if isinstance(live_gate.get("live_canary_config"), Mapping) else live_gate.get("live_canary_enabled"),
        "order_transport_submit_enabled": live_gate.get("order_transport_submit_enabled"),
        "live_trading_enabled": live_gate.get("live_trading_enabled"),
        "live_blocked": live_gate.get("live_blocked"),
        "operator_approved": live_gate.get("operator_approved"),
        "places_real_order": live_gate.get("places_real_order"),
        "exchange_action_taken": live_gate.get("exchange_action_taken"),
        "transport_order_submitted": transport.get("order_submitted"),
        "transport_writes_exchange_orders": transport.get("writes_exchange_orders"),
    }


def go_conditions() -> list[str]:
    return [
        "strict verifier exit = 0",
        "recorded-state verifier exit = 0",
        "critical failures = 0",
        "active-stale count = 0",
        "trusted prediction/replay/MTF evidence present",
        "live position state machine passes",
        "exchange/local reconciliation passes",
        "no open position",
        "no unexpected open orders",
        "futures available balance >= required minimum",
        "symbol is allowlisted",
        "notional <= tiny cap",
        "daily orders below cap",
        "daily loss below cap",
        "kill switch clear",
        "human operator arm present",
        "release mode explicitly changed from NON_LIVE only during activation",
        "order_transport_submit_enabled explicitly true only during activation",
        "live_canary_enabled explicitly true only during activation",
        "no leverage mutation",
        "no margin mode mutation",
    ]


def no_go_conditions() -> list[str]:
    return [
        "Pass 2B still insufficient and execution-validation acknowledgement missing",
        "insufficient futures available balance",
        "strict verifier nonzero",
        "recorded-state verifier nonzero",
        "active-stale > 0",
        "missing replay snapshot",
        "missing MTF snapshot",
        "exchange/local drift",
        "stale signed read",
        "unexpected open order",
        "existing open position",
        "unsupported symbol",
        "min notional/filter failure",
        "candidate notional not proven from signed mark price",
        "kill switch active",
        "human arm missing",
        "leverage mutation required",
        "margin mutation required",
        "any submit-enabled key unexpectedly armed before activation sequence",
    ]


def required_human_acknowledgements() -> list[str]:
    return [
        "I understand Pass 2B did not prove trading edge.",
        "I understand this is an execution-path validation canary only.",
        "I accept that the tiny order can lose money.",
        "I confirm the notional cap.",
        "I confirm max daily loss.",
        "I confirm no leverage or margin mutation.",
        "I confirm kill switch tested.",
        "I confirm manual disarm command is ready.",
    ]


def activation_sequence() -> list[str]:
    return [
        "Do not run until every go condition is true and operator acknowledgements are recorded by an approved manual workflow.",
        "Fund futures account externally if needed; the bot must not transfer or borrow funds.",
        "Rerun ./run_pass3c_tiny_live_canary_readiness_check and require PASS3C_READY_FOR_OPERATOR_REVIEW.",
        "Run strict verifier and recorded-state verifier one final time.",
        "Use the approved operator workflow to arm live_canary_enabled=true, release_mode=LIVE_CANARY_APPROVED, and order_transport_submit_enabled=true only for the tiny canary window.",
        "Run one tiny allowlisted canary order through the existing live transport.",
        "Immediately verify exchange order status, open position, fees, and lifecycle record.",
        "Disarm live submit after the canary window.",
    ]


def rollback_disarm_checklist() -> list[str]:
    return [
        "cd v2 && ../.venv/bin/python -m v2.backend.app.cli.v2_live_submit_disarm --redis-url redis://127.0.0.1:6379/0 --reason pass3c_manual_disarm",
        "./run_pass3c_tiny_live_canary_readiness_check --redis-url redis://127.0.0.1:6379/0 --output-dir pass3c_tiny_live_canary_readiness",
        "Use Binance read-only open-orders check for the canary symbol; do not cancel from this readiness command.",
        "Use Binance read-only positions/account check for the canary symbol.",
        "./export_pipeline_trust_evidence --redis-url redis://127.0.0.1:6379/0 --output-dir pipeline_trust_evidence_pass3c",
        "./verify_pipeline_trust --input pipeline_trust_evidence_pass3c/<run> --output-dir pipeline_trust_evidence_pass3c/<run>/report --strict-unknown",
        ".venv/bin/python -m v2.backend.app.cli.run_recorded_state_verification --input pipeline_trust_evidence_pass3c/<run> --output-dir recorded_state_verification_pass3c/<run>",
        "Inspect v2:live_order_transport:status, v2:live_gate:state, and v2:trader:execution_state.",
    ]


def render_markdown(report: Mapping[str, Any]) -> str:
    balance = report.get("futures_balance") if isinstance(report.get("futures_balance"), Mapping) else {}
    config = report.get("canary_config") if isinstance(report.get("canary_config"), Mapping) else {}
    live = report.get("live_control_state") if isinstance(report.get("live_control_state"), Mapping) else {}
    candidate = report.get("candidate") if isinstance(report.get("candidate"), Mapping) else {}
    notional = report.get("notional_validation") if isinstance(report.get("notional_validation"), Mapping) else {}
    return "\n".join(
        [
            f"# Pass 3C Tiny Live Canary Activation Plan: {report.get('run_id')}",
            "",
            f"Generated: `{report.get('generated_at')}`",
            "",
            "Scope: activation planning and readiness only. No live trading was enabled and no order was submitted.",
            "",
            "## Result",
            "",
            "| Field | Value |",
            "|---|---:|",
            f"| Readiness status | `{report.get('status')}` |",
            f"| Execution-validation canary acknowledged | `{report.get('execution_validation_canary_acknowledged')}` |",
            f"| Canary intent | `{report.get('canary_intent')}` |",
            f"| Strict critical failures | `{(report.get('strict_status') or {}).get('critical_failures')}` |",
            f"| Recorded-state critical failures | `{(report.get('recorded_state_status') or {}).get('critical_failures')}` |",
            f"| Trusted predictions | `{(report.get('trusted_evidence') or {}).get('trusted_prediction_count')}` |",
            f"| Replay snapshots | `{(report.get('trusted_evidence') or {}).get('replay_snapshot_count')}` |",
            f"| MTF snapshots | `{(report.get('trusted_evidence') or {}).get('mtf_snapshot_count')}` |",
            f"| Available futures balance | `{balance.get('available_balance_usdt')}` |",
            f"| Minimum required balance | `{balance.get('minimum_required_usdt')}` |",
            f"| Signed mark price | `{notional.get('signed_mark_price')}` |",
            f"| Computed notional | `{notional.get('computed_notional_usd')}` |",
            f"| Candidate notional | `{notional.get('candidate_notional_usd')}` |",
            f"| Notional validation | `{notional.get('valid')}` |",
            f"| Submit allowed | `{report.get('submit_allowed')}` |",
            f"| Live order submitted | `{report.get('live_order_submitted')}` |",
            f"| Exchange action taken | `{report.get('exchange_action_taken')}` |",
            "",
            "## Pass status",
            "",
            "| Gate | Status |",
            "|---|---|",
            "| Pass 1A live submit disarmed | complete |",
            "| Pass 2A trusted prediction + replay + MTF | complete |",
            "| Pass 2B edge framework | complete |",
            f"| Pass 2B edge result | `{(report.get('pass2b_summary') or {}).get('verdict')}` |",
            "| Pass 3A live-canary safety implementation | complete |",
            "| Pass 3B exact live-path dry run | complete, blocked by insufficient available balance |",
            "",
            "Pass 2B is still `INSUFFICIENT_SAMPLE`; any future live canary is execution-path validation only, not strategy or profitability validation.",
            "",
            "## Current live-control state",
            "",
            "```json",
            json.dumps(live, indent=2, sort_keys=True),
            "```",
            "",
            "## Tiny canary configuration",
            "",
            "```json",
            json.dumps({"candidate": candidate, "config": config, "balance": balance}, indent=2, sort_keys=True),
            "```",
            "",
            "## Candidate notional and exchange filter validation",
            "",
            "```json",
            json.dumps(notional, indent=2, sort_keys=True),
            "```",
            "",
            "## Blockers",
            "",
            "```json",
            json.dumps(report.get("blockers") or [], indent=2, sort_keys=True),
            "```",
            "",
            "## Required human acknowledgements",
            "",
            "\n".join(f"- {item}" for item in report.get("required_human_acknowledgements") or []),
            "",
            "## Go conditions",
            "",
            "\n".join(f"- {item}" for item in report.get("go_conditions") or []),
            "",
            "## No-go conditions",
            "",
            "\n".join(f"- {item}" for item in report.get("no_go_conditions") or []),
            "",
            "## Activation sequence (not run)",
            "",
            "\n".join(f"{idx}. {item}" for idx, item in enumerate(report.get("activation_sequence_not_run") or [], start=1)),
            "",
            "## Rollback / disarm checklist",
            "",
            "\n".join(f"- `{item}`" if item.startswith(("./", "cd ", ".venv")) else f"- {item}" for item in report.get("rollback_disarm_checklist") or []),
            "",
            "## Safety result",
            "",
            "- `live_canary_enabled` was not changed.",
            "- `order_transport_submit_enabled` was not changed.",
            "- `live_trading_enabled` was not changed.",
            "- No approval token was created.",
            "- No live order was submitted.",
            "- No exchange state was mutated.",
            "- No leverage or margin mode mutation was performed.",
        ]
    ) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
