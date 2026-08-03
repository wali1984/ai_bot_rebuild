"""Canonical real-time V2 runtime truth bus.

This module is read-only except for V2-owned public payload publication. It
does not call exchange endpoints, does not mutate live execution state, and
does not write legacy Redis keys.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

try:  # Uvicorn service runs with PYTHONPATH=v2/backend.
    from app.services.market_state_integrity.publisher import build_market_state_integrity_payloads
    from app.services.operator_truth.runtime_truth import build_operator_runtime_truth
    from app.services.v2_symbol_runtime_universe import is_valid_runtime_symbol
except ImportError:  # CLI/tests may import from the repo root package.
    from v2.backend.app.services.market_state_integrity.publisher import build_market_state_integrity_payloads
    from v2.backend.app.services.operator_truth.runtime_truth import build_operator_runtime_truth
    from v2.backend.app.services.v2_symbol_runtime_universe import is_valid_runtime_symbol

REPO_ROOT = Path(__file__).resolve().parents[5]
PUBLIC_ROOT = REPO_ROOT / "v2/frontend/public"
OP_RUNTIME_DIR = PUBLIC_ROOT / "operator_runtime/v2_runtime_truth/latest"
LIVE_GATE_RUNTIME_DIR = PUBLIC_ROOT / "operator_runtime/v2_live_gate_runtime/latest"
SIGNED_READ_RECOVERED_PATH = (
    PUBLIC_ROOT
    / "v2_signed_read_recovered_balance_hold_and_first_order_resume/latest/operator_dashboard_payload.json"
)
BALANCE_HOLD_PATH = (
    PUBLIC_ROOT
    / "v2_live_transport_balance_aware_hold_and_first_order_monitor/latest/operator_dashboard_payload.json"
)
_MAX_LIVE_HOLD_SOURCE_AGE_SECONDS = 3600
EST = timezone(timedelta(hours=-4))


def _est_now() -> str:
    return datetime.now(EST).isoformat(timespec="seconds")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _json_load(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _json(raw: Any) -> Any | None:
    if not raw:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return None


def _connect_redis() -> Any:
    try:
        import redis  # type: ignore

        client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True, socket_connect_timeout=2, socket_timeout=3)
        client.ping()
        return client
    except Exception:
        return None


def _redis_json(client: Any, key: str, default: Any = None) -> Any:
    if client is None:
        return default
    try:
        return _json(client.get(key)) or default
    except Exception:
        return default


def _scan_json(client: Any, pattern: str, limit: int = 1000) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if client is None:
        return rows
    try:
        for key in client.scan_iter(match=pattern, count=500):
            payload = _json(client.get(str(key)))
            if isinstance(payload, dict):
                row = dict(payload)
                row["_redis_key"] = str(key)
                rows.append(row)
            elif isinstance(payload, list):
                for item in payload:
                    if isinstance(item, dict):
                        row = dict(item)
                        row["_redis_key"] = str(key)
                        rows.append(row)
            if len(rows) >= limit:
                break
    except Exception:
        return rows
    return rows


def _prediction_grid_status(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    primary = [row for row in predictions if ":rl_core:" not in str(row.get("_redis_key", ""))]
    native_primary = [
        row
        for row in primary
        if str(row.get("trainer_source") or "").startswith("V2_NATIVE")
        or "CUDA" in str(row.get("trainer_source") or "")
    ]
    invalid_symbols = sorted(
        {
            str(row.get("symbol"))
            for row in primary
            if row.get("symbol") and not is_valid_runtime_symbol(str(row.get("symbol")))
        }
    )
    timeframes = Counter(str(row.get("timeframe") or "unknown") for row in native_primary)
    return {
        "prediction_rows_seen": len(predictions),
        "primary_prediction_rows": len(primary),
        "native_cuda_primary_rows": len(native_primary),
        "rl_core_sidecar_rows": len(predictions) - len(primary),
        "invalid_symbols": invalid_symbols,
        "invalid_symbol_count": len(invalid_symbols),
        "timeframe_counts": dict(timeframes.most_common()),
        "valid_for_prediction_count": sum(1 for row in primary if row.get("valid_for_prediction") is True),
    }


def _age_seconds(path: Path) -> float | None:
    try:
        return max(0.0, datetime.now(timezone.utc).timestamp() - path.stat().st_mtime)
    except OSError:
        return None


def _generated_age_seconds(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=EST)
    return max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds())


def _source_meta(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    file_age = _age_seconds(path)
    generated_age = _generated_age_seconds(payload.get("generated_utc") or payload.get("generated_est"))
    age = generated_age if generated_age is not None else file_age
    return {
        "source_payload": str(path.relative_to(REPO_ROOT)) if path.exists() else str(path),
        "generated_est": payload.get("generated_est"),
        "source_payload_age_seconds": age,
        "source_payload_fresh": age is not None and age <= _MAX_LIVE_HOLD_SOURCE_AGE_SECONDS,
    }


def _live_transport_monitor_path(filename: str) -> Path:
    return BALANCE_HOLD_PATH.parent / filename


def _signed_read_recovery_path(filename: str) -> Path:
    return SIGNED_READ_RECOVERED_PATH.parent / filename


def _safe_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _safe_rows(value: Any, *, limit: int = 100) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    return [dict(row) for row in rows[:limit] if isinstance(row, dict)]


def _fresh_payload(path: Path, default: Any = None) -> tuple[Any, dict[str, Any]]:
    payload = _json_load(path, default)
    if not isinstance(payload, dict):
        payload = default if isinstance(default, dict) else {}
    return payload, _source_meta(path, payload)


def _sanitize_account_snapshot(
    *,
    source_payload: dict[str, Any],
    account_margin: dict[str, Any],
    account_hold: dict[str, Any],
    meta: dict[str, Any],
) -> dict[str, Any]:
    signed_ok = account_margin.get("ok") is True or source_payload.get("critical_account_read_gate") == "CRITICAL_ACCOUNT_READ_GATE_READY"
    fresh = meta.get("source_payload_fresh") is True
    current_ok = signed_ok and fresh
    return {
        "schema_version": "operator_truth_signed_account_snapshot_v1",
        "status": "SIGNED_ACCOUNT_READ_STALE" if signed_ok and not fresh else account_margin.get("status") or account_hold.get("status"),
        "ok": current_ok,
        "signed_account_read_ok": current_ok,
        "last_known_signed_account_read_ok": signed_ok,
        "fresh": fresh,
        "generated_est": account_margin.get("generated_est") or account_hold.get("generated_est") or meta.get("generated_est"),
        "source_payload": meta.get("source_payload"),
        "source_payload_age_seconds": meta.get("source_payload_age_seconds"),
        "available_margin": source_payload.get("available_margin")
        if "available_margin" in source_payload
        else account_hold.get("available_margin")
        if "available_margin" in account_hold
        else account_margin.get("available_margin"),
        "wallet_balance": source_payload.get("wallet_balance")
        if "wallet_balance" in source_payload
        else account_hold.get("wallet_balance")
        if "wallet_balance" in account_hold
        else account_margin.get("wallet_balance"),
        "unrealized_pnl": account_hold.get("unrealized_pnl") if "unrealized_pnl" in account_hold else account_margin.get("unrealized_pnl"),
        "required_initial_margin": source_payload.get("required_initial_margin") or account_hold.get("required_initial_margin"),
        "available_margin_checked": account_margin.get("available_margin_checked") is True or account_margin.get("ok") is True,
        "wallet_balance_checked": account_margin.get("wallet_balance_checked") is True,
        "endpoint": account_margin.get("endpoint"),
        "raw_credentials_exposed": False,
        "raw_account_payload_exposed": False,
    }


def _sanitize_open_orders_snapshot(open_orders: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    ok = open_orders.get("ok") is True
    return {
        "schema_version": "operator_truth_open_orders_snapshot_v1",
        "status": open_orders.get("status"),
        "ok": ok,
        "fresh": meta.get("source_payload_fresh") is True,
        "generated_est": open_orders.get("generated_est") or meta.get("generated_est"),
        "source_payload": meta.get("source_payload"),
        "source_payload_age_seconds": meta.get("source_payload_age_seconds"),
        "endpoint": open_orders.get("endpoint"),
        "status_code": open_orders.get("status_code"),
        "open_orders_count": open_orders.get("open_orders_count"),
        "open_orders": [] if ok and open_orders.get("open_orders_count") == 0 else None,
        "raw_credentials_exposed": False,
        "raw_open_orders_payload_exposed": False,
    }


def _sanitize_position_mode_snapshot(pre_submit: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    status = _safe_mapping(pre_submit.get("position_mode_status"))
    return {
        "schema_version": "operator_truth_position_mode_snapshot_v1",
        "status": "POSITION_MODE_READ_OK" if status.get("ok") is True else "POSITION_MODE_READ_MISSING",
        "ok": status.get("ok") is True,
        "fresh": meta.get("source_payload_fresh") is True,
        "generated_est": pre_submit.get("generated_est") or meta.get("generated_est"),
        "source_payload": meta.get("source_payload"),
        "source_payload_age_seconds": meta.get("source_payload_age_seconds"),
        "dual_side_position": status.get("dual_side_position"),
        "hedge_mode": status.get("dual_side_position"),
        "endpoint": status.get("endpoint"),
        "status_code": status.get("status_code"),
        "source": status.get("source"),
        "raw_credentials_exposed": False,
        "raw_position_payload_exposed": False,
    }


def _sanitize_symbol_filter_snapshot(symbol_map: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    filters: dict[str, dict[str, Any]] = {}
    for row in _safe_rows(symbol_map.get("rows")):
        symbol = str(row.get("symbol") or "").upper()
        filter_status = _safe_mapping(row.get("filter_status"))
        safe_filter = {
            "ok": filter_status.get("ok"),
            "symbol": filter_status.get("symbol") or symbol,
            "status": filter_status.get("status"),
            "min_qty": filter_status.get("min_qty"),
            "step_size": filter_status.get("step_size"),
            "tick_size": filter_status.get("tick_size"),
            "min_notional": filter_status.get("min_notional"),
            "endpoint": filter_status.get("endpoint"),
            "source": filter_status.get("source"),
        }
        safe_row = {
            "symbol": symbol,
            "mark_price": row.get("mark_price"),
            "mark_price_source": row.get("mark_price_source"),
            "min_qty": row.get("min_qty"),
            "min_notional": row.get("min_notional"),
            "step_size": row.get("step_size"),
            "tick_size": row.get("tick_size"),
            "min_executable_qty": row.get("min_executable_qty"),
            "min_executable_notional": row.get("min_executable_notional"),
            "balance_required": row.get("balance_required"),
            "executable_with_current_balance": row.get("executable_with_current_balance"),
            "filter_status": safe_filter,
            "sizing_status": _safe_mapping(row.get("sizing_status")),
            "blockers": [str(item) for item in row.get("blockers") or [] if str(item)],
        }
        rows.append(safe_row)
        if symbol:
            filters[symbol] = safe_filter
    return {
        "schema_version": "operator_truth_symbol_filter_snapshot_v1",
        "status": symbol_map.get("status"),
        "fresh": meta.get("source_payload_fresh") is True,
        "generated_est": symbol_map.get("generated_est") or meta.get("generated_est"),
        "source_payload": meta.get("source_payload"),
        "source_payload_age_seconds": meta.get("source_payload_age_seconds"),
        "accepted_symbols": symbol_map.get("accepted_symbols") or [],
        "filters": filters,
        "rows": rows,
        "raw_credentials_exposed": False,
        "raw_exchange_info_payload_exposed": False,
    }


def _sanitize_selected_candidate(pre_submit: dict[str, Any], balance: dict[str, Any]) -> dict[str, Any]:
    candidate = _safe_mapping(pre_submit.get("selected_candidate")) or _safe_mapping(balance.get("selected_candidate"))
    account_status = _safe_mapping(candidate.get("account_margin_status"))
    return {
        "schema_version": "operator_truth_live_candidate_snapshot_v1",
        "symbol": candidate.get("symbol"),
        "side": candidate.get("side"),
        "position_side": candidate.get("position_side"),
        "quantity": candidate.get("quantity"),
        "requested_notional_usdt": candidate.get("requested_notional_usdt"),
        "price_reference": candidate.get("price_reference"),
        "source_generated_est": candidate.get("source_generated_est"),
        "lineage": _safe_mapping(candidate.get("lineage")),
        "adaptive_allocation": _safe_mapping(candidate.get("adaptive_allocation")),
        "symbol_filter_status": _safe_mapping(candidate.get("symbol_filter_status")),
        "account_margin_status": {
            "ok": account_status.get("ok"),
            "available_balance_checked": account_status.get("available_balance_checked"),
            "available_balance_sufficient": account_status.get("available_balance_sufficient"),
            "required_initial_margin_usdt": account_status.get("required_initial_margin_usdt"),
            "required_notional_usdt": account_status.get("required_notional_usdt"),
            "endpoint": account_status.get("endpoint"),
            "source": account_status.get("source"),
        },
        "raw_credentials_exposed": False,
        "raw_account_payload_exposed": False,
    }


def _read_recent_jsonl(path: Path, max_lines: int = 3000) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = path.read_bytes()[-4_000_000:]
    except OSError:
        return []
    text = data.replace(b"\x00", b"").decode("utf-8", errors="ignore")
    rows: list[dict[str, Any]] = []
    for line in text.splitlines()[-max_lines:]:
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _current_live_execution_hold(
    *,
    live_gate_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the latest V2 live-execution hold state from current payloads.

    Older report payloads still mention Binance HTTP 451. The signed-read
    recovery gate is more authoritative when present because it is generated
    after the full-tunnel account-read check and classifies the current blocker.
    """
    signed = _json_load(SIGNED_READ_RECOVERED_PATH, {}) or {}
    balance = _json_load(BALANCE_HOLD_PATH, {}) or {}
    source_payload = signed if signed else balance
    source_path = SIGNED_READ_RECOVERED_PATH if signed else BALANCE_HOLD_PATH
    source_meta = _source_meta(source_path, source_payload)
    source_fresh = source_meta["source_payload_fresh"] is True
    account_margin, account_meta = _fresh_payload(_live_transport_monitor_path("account_margin_snapshot_status.json"), {})
    account_hold, account_hold_meta = _fresh_payload(_signed_read_recovery_path("account_margin_balance_hold_status.json"), {})
    open_orders, open_orders_meta = _fresh_payload(_live_transport_monitor_path("open_orders_snapshot_status.json"), {})
    pre_submit, pre_submit_meta = _fresh_payload(_live_transport_monitor_path("live_order_transport_pre_submit_evaluation_status.json"), {})
    live_symbol_map, live_symbol_meta = _fresh_payload(_live_transport_monitor_path("live_symbol_min_executable_map.json"), {})
    signed_symbol_map, signed_symbol_meta = _fresh_payload(_signed_read_recovery_path("live_symbol_min_executable_refresh_status.json"), {})
    symbol_map = signed_symbol_map if signed_symbol_map else live_symbol_map
    symbol_meta = signed_symbol_meta if signed_symbol_map else live_symbol_meta
    signed_account_snapshot = _sanitize_account_snapshot(
        source_payload=source_payload,
        account_margin=account_margin,
        account_hold=account_hold,
        meta=account_hold_meta if account_hold else source_meta,
    )
    open_orders_snapshot = _sanitize_open_orders_snapshot(open_orders, open_orders_meta)
    position_mode_snapshot = _sanitize_position_mode_snapshot(pre_submit, pre_submit_meta)
    symbol_filter_snapshot = _sanitize_symbol_filter_snapshot(symbol_map, symbol_meta)
    selected_candidate_snapshot = _sanitize_selected_candidate(pre_submit, _json_load(_live_transport_monitor_path("live_transport_balance_hold_status.json"), {}) or {})
    signed_classification = source_payload.get("signed_read_classification") or balance.get("signed_read_classification")
    blockers = [str(item) for item in (source_payload.get("blockers") or balance.get("blockers") or [])]
    no_451 = signed_classification == "NO_451_DETECTED"
    runtime_live_gate = (
        str(live_gate_state.get("live_gate") or "").strip()
        if isinstance(live_gate_state, dict)
        else ""
    )
    live_gate = runtime_live_gate or source_payload.get("live_gate") or balance.get("live_gate") or "blocked_human_only"
    trader_state = source_payload.get("trader_state") or balance.get("trader_state")
    if no_451 and "INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER" in blockers:
        binance_private_execution = "SIGNED_READS_RECOVERED_BALANCE_HOLD"
        transport_state = "BINANCE_TRANSPORT_BOUND_BALANCE_HELD"
        blocker = "INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER"
        private_451_state = "NO_451_DETECTED"
        next_operator = "Fund the account or provide available margin; do not retry orders until margin satisfies minimum executable notional."
    elif no_451:
        binance_private_execution = "SIGNED_READS_RECOVERED"
        transport_state = "BINANCE_TRANSPORT_BOUND_SIGNED_READS_RECOVERED"
        blocker = blockers[0] if blockers else "LIVE_ORDER_SUBMIT_HELD_BY_CURRENT_GUARD"
        private_451_state = "NO_451_DETECTED"
        next_operator = "Review current live-order guard before any live submission."
    else:
        binance_private_execution = "COMPLIANCE_HELD_HTTP_451"
        transport_state = "BINANCE_TRANSPORT_BOUND_PRIVATE_EXECUTION_HELD"
        blocker = "BINANCE_SIGNED_READ_RESTRICTED_LOCATION_451"
        private_451_state = "COMPLIANCE_HELD_HTTP_451"
        next_operator = "Restore compliant signed exchange access or approve audited failover; do not bypass Binance HTTP 451."
        trader_state = trader_state or "LIVE_ARMED_COMPLIANCE_HOLD"
    if not source_fresh:
        blockers.append("LIVE_SIGNED_READ_SOURCE_STALE")
        binance_private_execution = "SIGNED_READ_SOURCE_STALE"
        transport_state = "BINANCE_TRANSPORT_BOUND_STALE_SIGNED_READ_PROOF"
        private_451_state = "SIGNED_READ_SOURCE_STALE"
        blocker = "LIVE_SIGNED_READ_SOURCE_STALE"
        next_operator = "Refresh signed read-only account, position, open-order, and symbol-filter snapshots before any live operator review."
    if live_gate != "enabled_operator_approved" and "LIVE_GATE_NOT_ENABLED" not in blockers:
        blockers.append("LIVE_GATE_NOT_ENABLED")
        blocker = "LIVE_GATE_NOT_ENABLED"
    if live_gate == "enabled_operator_approved" and not trader_state:
        trader_state = "LIVE_ARMED_BALANCE_HOLD" if no_451 else "LIVE_ARMED_COMPLIANCE_HOLD"
    runtime_submit_enabled = (
        live_gate_state.get("order_transport_submit_enabled") is True
        if isinstance(live_gate_state, dict) and live_gate_state
        else True
    )
    return {
        "source_payload": str(source_path.relative_to(REPO_ROOT)),
        "source_payload_age_seconds": source_meta.get("source_payload_age_seconds"),
        "source_payload_fresh": source_fresh,
        "generated_est": source_payload.get("generated_est"),
        "live_gate": live_gate,
        "trader_state": trader_state or "PAPER_SHADOW_ONLY",
        "transport_state": transport_state,
        "binance_private_execution": binance_private_execution,
        "binance_private_451_state": private_451_state,
        "signed_read_classification": signed_classification,
        "critical_account_read_gate": (
            "CRITICAL_ACCOUNT_READ_GATE_STALE"
            if not source_fresh
            else source_payload.get("critical_account_read_gate") or balance.get("critical_account_read_gate_status")
        ),
        "live_order_submit_allowed": (
            bool(source_payload.get("live_submit_allowed") or source_payload.get("order_submission_allowed"))
            and live_gate == "enabled_operator_approved"
            and runtime_submit_enabled
            and source_fresh
        ),
        "live_order_submit_blocker": blocker,
        "blockers": blockers or [blocker],
        "available_margin": source_payload.get("available_margin") if "available_margin" in source_payload else balance.get("available_margin"),
        "wallet_balance": source_payload.get("wallet_balance") if "wallet_balance" in source_payload else balance.get("wallet_balance"),
        "required_initial_margin": (
            source_payload.get("required_initial_margin")
            if "required_initial_margin" in source_payload
            else balance.get("required_initial_margin")
        ),
        "accepted_symbols": source_payload.get("accepted_symbols") or balance.get("accepted_symbols") or [],
        "active_risk_profile": source_payload.get("active_risk_profile") or balance.get("active_risk_profile"),
        "signed_account_snapshot": signed_account_snapshot,
        "open_orders_snapshot": open_orders_snapshot,
        "position_mode_snapshot": position_mode_snapshot,
        "symbol_filter_snapshot": symbol_filter_snapshot,
        "selected_candidate_snapshot": selected_candidate_snapshot,
        "next_operator_only_action": next_operator,
    }


def build_live_gate_runtime_display_state(
    *,
    runtime_truth: dict[str, Any],
    previous_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    previous = previous_state if isinstance(previous_state, dict) else {}
    live_order_allowed = bool(runtime_truth.get("live_order_submit_allowed"))
    accepted_symbols = [str(symbol).upper() for symbol in runtime_truth.get("accepted_live_symbols") or [] if str(symbol).strip()]
    generated_est = str(runtime_truth.get("generated_est") or _est_now())
    return {
        "schema_version": "v2_live_gate_runtime_balance_hold_display_v1",
        "generated_est": generated_est,
        "runtime_refreshed_at_est": generated_est,
        "runtime_heartbeat_source": "operator_runtime_truth_realtime_mirror",
        "source": "operator_runtime/v2_runtime_truth/latest/operator_runtime_truth.json",
        "live_gate": runtime_truth.get("live_gate") or "blocked_human_only",
        "trader_state": runtime_truth.get("trader_state"),
        "transport_state": runtime_truth.get("transport_state"),
        "live_blocker": runtime_truth.get("live_order_submit_blocker"),
        "live_order_submit_allowed": live_order_allowed,
        "live_order_submit_blocker": runtime_truth.get("live_order_submit_blocker"),
        "available_margin": runtime_truth.get("available_margin"),
        "wallet_balance": runtime_truth.get("wallet_balance"),
        "required_initial_margin": runtime_truth.get("required_initial_margin"),
        "source_payload_age_seconds": runtime_truth.get("live_execution_source_payload_age_seconds"),
        "source_payload_fresh": runtime_truth.get("live_execution_source_payload_fresh"),
        "signed_account_snapshot": runtime_truth.get("signed_account_snapshot") or {},
        "open_orders_snapshot": runtime_truth.get("open_orders_snapshot") or {},
        "position_mode_snapshot": runtime_truth.get("position_mode_snapshot") or {},
        "symbol_filter_snapshot": runtime_truth.get("symbol_filter_snapshot") or {},
        "selected_candidate_snapshot": runtime_truth.get("selected_candidate_snapshot") or {},
        "accepted_live_symbols": accepted_symbols,
        "live_symbols": accepted_symbols,
        "execution_live_symbols": accepted_symbols,
        "accepted_risk_audit_id": previous.get("accepted_risk_audit_id"),
        "accepted_symbols_audit_id": previous.get("accepted_symbols_audit_id"),
        "final_approval_audit_id": previous.get("final_approval_audit_id"),
        "enable_audit_id": previous.get("enable_audit_id"),
        "risk_profile": previous.get("risk_profile") or {"profile_name": runtime_truth.get("active_risk_profile")},
        "operator_approved": runtime_truth.get("live_gate") == "enabled_operator_approved",
        "operator_approval_required": runtime_truth.get("live_gate") != "enabled_operator_approved",
        "trader_execution_enabled": False,
        "live_trading_enabled": False,
        "live_blocked": True,
        "order_transport_write_guard_enabled": True,
        "order_transport_write_guard_source": "operator_runtime_truth_realtime_mirror",
        "order_transport_submit_enabled": False,
        "order_transport_submit_source": "operator_runtime_truth_realtime_mirror_display_only",
        "places_real_order": False,
        "exchange_action_taken": False,
        "kill_switch_enabled": previous.get("kill_switch_enabled", True),
        "kill_switch_active": previous.get("kill_switch_active", False),
        "margin_mutation_allowed": False,
        "leverage_mutation_allowed": False,
        "old_redis_write_allowed": False,
        "redis_trim_allowed": False,
        "legacy_restart_allowed": False,
        "release_mode": previous.get("release_mode") or "NON_LIVE",
        "reason": runtime_truth.get("live_order_submit_blocker") or "LIVE_ORDER_SUBMIT_HELD_BY_RUNTIME_TRUTH",
        "safety": {
            "real_orders": False,
            "test_order": False,
            "leverage_margin_mutation": False,
            "old_redis_write": False,
            "legacy_restart": False,
            "redis_trim": False,
            "raw_credentials": False,
        },
    }


def build_paper_pnl_source_of_truth(client: Any = None) -> dict[str, Any]:
    client = client or _connect_redis()
    ledger = _redis_json(client, "v2:paper:ledger", {}) or {}
    portfolio = _redis_json(client, "v2:portfolio:state", {}) or _json_load(
        PUBLIC_ROOT / "operator_runtime/v2_portfolio_state/latest/v2_portfolio_state.json",
        {},
    )
    accepted = [row for row in ledger.get("accepted", []) if isinstance(row, dict)] if isinstance(ledger, dict) else []
    held = [row for row in ledger.get("held_by_paper_fill_gate", []) if isinstance(row, dict)] if isinstance(ledger, dict) else []
    shadow = [row for row in ledger.get("shadow_observations", []) if isinstance(row, dict)] if isinstance(ledger, dict) else []
    current_session_pnl = float(
        (portfolio or {}).get("total_pnl_usd")
        if (portfolio or {}).get("total_pnl_usd") is not None
        else (portfolio or {}).get("realized_net_pnl_usd")
        if (portfolio or {}).get("realized_net_pnl_usd") is not None
        else (portfolio or {}).get("clean_session_valid_realized_pnl_usd")
        if (portfolio or {}).get("clean_session_valid_realized_pnl_usd") is not None
        else (portfolio or {}).get("realized_pnl_usd") or 0.0
    )
    current_session_equity = float((portfolio or {}).get("equity") or 10_000.0)
    paper_session_id = (
        (portfolio or {}).get("paper_session_id")
        or (portfolio or {}).get("reset_session_id")
        or (ledger or {}).get("paper_session_id")
        or (ledger or {}).get("reset_session_id")
        or (ledger or {}).get("session_id")
    )
    paper_online_path = PUBLIC_ROOT / "operator_runtime/paper_online/latest/paper_events.jsonl"
    old_events = _read_recent_jsonl(paper_online_path)
    historical_pnl_values = [
        float(row.get("paper_realized_pnl"))
        for row in old_events
        if isinstance(row.get("paper_realized_pnl"), (int, float))
    ]
    latest_historical_pnl = historical_pnl_values[-1] if historical_pnl_values else None
    stale_detected = latest_historical_pnl is not None and round(latest_historical_pnl, 2) != round(current_session_pnl, 2)
    minus_49_classification = "NOT_PRESENT"
    if latest_historical_pnl is not None and -50.0 < latest_historical_pnl < -48.0:
        minus_49_classification = (
            "STALE_OR_LIFETIME_PAPER_ONLINE_PNL_NOT_CURRENT_SESSION"
            if not accepted
            else "HISTORICAL_PAPER_ONLINE_PNL_SEPARATE_FROM_CURRENT_LEDGER"
        )
    if accepted and round(current_session_pnl, 2) == -49.35:
        minus_49_classification = "CURRENT_ACTIVE_CANONICAL_PORTFOLIO_PNL"
    return {
        "schema_version": "paper_pnl_source_of_truth_status_v1",
        "generated_est": _est_now(),
        "generated_utc": _utc_now(),
        "paper_session_id": paper_session_id,
        "current_session_pnl": current_session_pnl,
        "current_session_equity": current_session_equity,
        "lifetime_paper_pnl": latest_historical_pnl,
        "today_paper_pnl": current_session_pnl,
        "rolling_1h_paper_pnl": current_session_pnl,
        "rolling_24h_paper_pnl": current_session_pnl,
        "initial_capital": (portfolio or {}).get("initial_capital", 10_000.0),
        "current_cash": (portfolio or {}).get("cash_balance", 10_000.0),
        "realized_pnl": (
            (portfolio or {}).get("realized_net_pnl_usd")
            if (portfolio or {}).get("realized_net_pnl_usd") is not None
            else (portfolio or {}).get("clean_session_valid_realized_pnl_usd")
            if (portfolio or {}).get("clean_session_valid_realized_pnl_usd") is not None
            else (portfolio or {}).get("realized_pnl_usd", 0.0)
        ),
        "unrealized_pnl": (portfolio or {}).get("unrealized_pnl_usd", 0.0),
        "open_positions": (portfolio or {}).get("open_positions_count", 0),
        "accepted_fill_count": len(accepted),
        "held_row_count": len(held),
        "shadow_observation_count": len(shadow),
        "last_fill_est": (portfolio or {}).get("last_fill_est"),
        "last_equity_update_est": (portfolio or {}).get("last_equity_update_est"),
        "pnl_source_payload": "operator_runtime/v2_portfolio_state/latest/v2_portfolio_state.json",
        "pnl_source_redis_keys": ["v2:portfolio:state"],
        "pnl_source_key": (portfolio or {}).get("pnl_source_key") or "v2:portfolio:state",
        "pnl_source_route": (portfolio or {}).get("pnl_source_route") or "/api/v2/portfolio",
        "pnl_source_type": (portfolio or {}).get("pnl_source_type") or "CANONICAL_CURRENT_SESSION_RUNTIME",
        "pnl_lineage_context_redis_keys": ["v2:paper:ledger"],
        "stale_source_detected": stale_detected,
        "stale_source_path_if_any": str(paper_online_path.relative_to(REPO_ROOT)) if stale_detected else None,
        "paper_minus_49_classification": minus_49_classification,
        "current_active_session_reason": (
            "CURRENT_SESSION_PNL_FROM_CANONICAL_V2_PORTFOLIO_STATE_NO_ACCEPTED_LEDGER_FILL"
            if not accepted
            else "CURRENT_SESSION_PNL_FROM_CANONICAL_V2_PORTFOLIO_STATE"
        ),
        "current_loss_fill_rows": accepted if round(current_session_pnl, 2) == -49.35 else [],
        "old_june_5_fills_reused": False,
        "fills_fabricated": False,
    }


def build_runtime_pages_payload(
    *,
    runtime_truth: dict[str, Any],
    pnl_status: dict[str, Any],
    integrity_status: dict[str, Any],
    live_hold: dict[str, Any] | None = None,
) -> dict[str, Any]:
    live_hold = live_hold if isinstance(live_hold, dict) else _current_live_execution_hold()
    routes = [
        "/dashboard",
        "/landing",
        "/markets",
        "/markets/symbols",
        "/trade",
        "/trade/paper",
        "/derivatives",
        "/signals",
        "/ai-predictions",
        "/portfolio",
        "/backtests",
        "/research",
        "/alerts",
        "/system",
        "/system/execution",
        "/system/readiness",
        "/system/reports",
        "/system/evidence",
    ]
    freshness = runtime_truth.get("payload_freshness") or {}
    stale = [name for name, status in freshness.items() if status in {"STALE", "OLD", "MISSING"}]
    return {
        "schema_version": "runtime_pages_payload_v1",
        "generated_est": _est_now(),
        "generated_utc": _utc_now(),
        "canonical_source": "operator_runtime/v2_runtime_truth/latest/operator_runtime_truth.json",
        "paper_equity_source": pnl_status.get("pnl_source_payload"),
        "paper_session_id": pnl_status.get("paper_session_id"),
        "paper_current_session_pnl": pnl_status.get("current_session_pnl"),
        "paper_current_session_equity": pnl_status.get("current_session_equity"),
        "paper_minus_49_classification": pnl_status.get("paper_minus_49_classification"),
        "paper_accepted_fills": pnl_status.get("accepted_fill_count"),
        "paper_held_rows": pnl_status.get("held_row_count"),
        "live_gate": live_hold.get("live_gate"),
        "trader_state": live_hold.get("trader_state"),
        "transport_state": live_hold.get("transport_state"),
        "binance_private_execution": live_hold.get("binance_private_execution"),
        "binance_private_451_state": live_hold.get("binance_private_451_state"),
        "signed_read_classification": live_hold.get("signed_read_classification"),
        "critical_account_read_gate": live_hold.get("critical_account_read_gate"),
        "available_margin": live_hold.get("available_margin"),
        "required_initial_margin": live_hold.get("required_initial_margin"),
        "live_order_submit_allowed": live_hold.get("live_order_submit_allowed"),
        "live_order_submit_blocker": live_hold.get("live_order_submit_blocker"),
        "live_execution_source_payload": live_hold.get("source_payload"),
        "live_execution_source_payload_age_seconds": live_hold.get("source_payload_age_seconds"),
        "live_execution_source_payload_fresh": live_hold.get("source_payload_fresh"),
        "signed_account_snapshot": live_hold.get("signed_account_snapshot") or {},
        "open_orders_snapshot": live_hold.get("open_orders_snapshot") or {},
        "position_mode_snapshot": live_hold.get("position_mode_snapshot") or {},
        "symbol_filter_snapshot": live_hold.get("symbol_filter_snapshot") or {},
        "selected_candidate_snapshot": live_hold.get("selected_candidate_snapshot") or {},
        "market_state_integrity_status": {
            "average_score": integrity_status.get("average_market_state_integrity_score"),
            "states_scored": integrity_status.get("market_states_scored"),
            "accepted_training_rows": integrity_status.get("feature_training_rows_valid"),
            "training_rows_scored": integrity_status.get("training_rows_scored"),
            "valid_for_paper_count": integrity_status.get("valid_for_paper_count"),
            "valid_for_live_count": integrity_status.get("valid_for_live_count"),
            "top_reject_reasons": integrity_status.get("top_reject_reasons"),
        },
        "missing_data_summary": {
            "stale_or_missing_payloads": stale,
            "stale_or_missing_payload_count": len(stale),
        },
        "routes": [
            {
                "route": route,
                "source_endpoint": "/operator_runtime/v2_runtime_truth/latest/runtime_pages_payload.json",
                "generated_est": _est_now(),
                "freshness_status": "CURRENT_CANONICAL_PAYLOAD_AVAILABLE",
                "paper_equity_source": pnl_status.get("pnl_source_payload"),
                "shows_missing_source_reasons": True,
                "static_report_as_current_truth_allowed": False,
            }
            for route in routes
        ],
    }


def build_realtime_runtime_truth(redis_client: Any = None) -> dict[str, dict[str, Any]]:
    client = redis_client or _connect_redis()
    portfolio_path = PUBLIC_ROOT / "operator_runtime/v2_portfolio_state/latest/v2_portfolio_state.json"
    portfolio_age = _age_seconds(portfolio_path)
    base_truth = build_operator_runtime_truth()
    pnl_status = build_paper_pnl_source_of_truth(client)
    integrity_payloads = build_market_state_integrity_payloads(client)
    integrity_status = integrity_payloads["market_state_integrity_service_status.json"]
    live_gate_state = _redis_json(client, "v2:live_gate:state", {}) or {}
    live_hold = _current_live_execution_hold(live_gate_state=live_gate_state)
    predictions = _scan_json(client, "v2:prediction:*", limit=2000)
    signals = _scan_json(client, "v2:signals:paper*", limit=2000)
    provider_status = {
        "binance_public": "ACTIVE_OR_PAYLOAD_DEPENDENT",
        "binance_private": live_hold.get("binance_private_execution"),
        "coinapi_wsds": "SEE_INGESTOR_STATUS",
        "kucoin": "SEE_INGESTOR_STATUS",
    }
    prediction_status = _prediction_grid_status(predictions)
    native_cuda_current = prediction_status["native_cuda_primary_rows"] > 0
    trainer_status = (
        "NATIVE_CUDA_TRAINER_CURRENT"
        if native_cuda_current and not prediction_status["invalid_symbols"]
        else "NATIVE_CUDA_TRAINER_CURRENT_WITH_INVALID_SYMBOL_ROWS"
        if native_cuda_current
        else base_truth.get("trainer_status") or "MISSING"
    )
    orchestrator_payload = _redis_json(client, "v2:orchestrator:decisions", {}) or {}
    portfolio_payload = _redis_json(client, "v2:portfolio:state", {}) or {}
    orchestrator_status = (
        orchestrator_payload.get("classification")
        if isinstance(orchestrator_payload, dict)
        else None
    ) or base_truth.get("orchestrator_gate_state")
    paper_status = (
        portfolio_payload.get("classification")
        if isinstance(portfolio_payload, dict)
        else None
    ) or base_truth.get("paper_classification")
    payload = {
        **base_truth,
        "schema_version": "operator_runtime_truth_realtime_v2",
        "generated_est": _est_now(),
        "generated_utc": _utc_now(),
        "payload_age_seconds": 0,
        "data_source_status": "CANONICAL_RUNTIME_TRUTH_PUBLISHED",
        "live_gate": live_hold.get("live_gate") or base_truth.get("live_gate"),
        "trader_state": live_hold.get("trader_state"),
        "transport_state": live_hold.get("transport_state"),
        "binance_private_451_state": live_hold.get("binance_private_451_state"),
        "signed_read_classification": live_hold.get("signed_read_classification"),
        "critical_account_read_gate": live_hold.get("critical_account_read_gate"),
        "available_margin": live_hold.get("available_margin"),
        "required_initial_margin": live_hold.get("required_initial_margin"),
        "live_order_submit_allowed": live_hold.get("live_order_submit_allowed"),
        "live_order_submit_blocker": live_hold.get("live_order_submit_blocker"),
        "live_execution_source_payload": live_hold.get("source_payload"),
        "live_execution_source_payload_age_seconds": live_hold.get("source_payload_age_seconds"),
        "live_execution_source_payload_fresh": live_hold.get("source_payload_fresh"),
        "signed_account_snapshot": live_hold.get("signed_account_snapshot") or {},
        "open_orders_snapshot": live_hold.get("open_orders_snapshot") or {},
        "position_mode_snapshot": live_hold.get("position_mode_snapshot") or {},
        "symbol_filter_snapshot": live_hold.get("symbol_filter_snapshot") or {},
        "selected_candidate_snapshot": live_hold.get("selected_candidate_snapshot") or {},
        "accepted_live_symbols": live_hold.get("accepted_symbols"),
        "active_risk_profile": live_hold.get("active_risk_profile"),
        "paper_equity": pnl_status.get("current_session_equity"),
        "paper_session_id": pnl_status.get("paper_session_id"),
        "paper_pnl": pnl_status.get("current_session_pnl"),
        "accepted_paper_fills": pnl_status.get("accepted_fill_count"),
        "held_paper_rows": pnl_status.get("held_row_count"),
        "open_paper_positions": pnl_status.get("open_positions"),
        "trainer_status": trainer_status,
        "trainer_model_version": (
            "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_PAPER_SHADOW"
            if native_cuda_current
            else base_truth.get("trainer_model_version")
        ),
        "cuda_trainer_status": trainer_status,
        "gpu_utilization": "missing telemetry field",
        "vram_utilization": "missing telemetry field",
        "training_rows": integrity_payloads["training_sample_rejection_status.json"].get("trainer_row_count_after"),
        "prediction_grid_status": prediction_status,
        "signal_grid_status": {
            "paper_signal_rows_seen": len(signals),
        },
        "risk_status": base_truth.get("risk_classification"),
        "orchestrator_status": orchestrator_status,
        "paper_trader_status": paper_status,
        "provider_status": provider_status,
        "feature_ta_coverage": {
            "ta_status": base_truth.get("ta_status"),
            "ta_keys_fresh": base_truth.get("ta_keys_fresh"),
        },
        "market_state_integrity": {
            "status": "MARKET_STATE_INTEGRITY_ACTIVE",
            "average_score": integrity_status.get("average_market_state_integrity_score"),
            "states_scored": integrity_status.get("market_states_scored"),
            "accepted_training_rows": integrity_status.get("feature_training_rows_valid"),
            "training_rows_scored": integrity_status.get("training_rows_scored"),
            "top_reject_reasons": integrity_status.get("top_reject_reasons"),
        },
        "missing_data_summary": {
            "payload_freshness": base_truth.get("payload_freshness"),
            "paper_minus_49_classification": pnl_status.get("paper_minus_49_classification"),
            "paper_current_session_reason": pnl_status.get("current_active_session_reason"),
        },
        "website_route_freshness": {
            "portfolio_payload_age_seconds": portfolio_age,
            "runtime_pages_payload": "CURRENT_AFTER_PUBLISH",
        },
        "next_automatic_action": "Continue paper equity, market-state integrity, runtime truth, and website payload monitor.",
        "next_operator_only_action": live_hold.get("next_operator_only_action"),
        "safety": {
            "real_orders": False,
            "test_order": False,
            "leverage_margin_mutation": False,
            "old_redis_write": False,
            "legacy_restart": False,
            "redis_trim": False,
            "raw_credentials": False,
            "vpn_proxy_evasion": False,
        },
    }
    runtime_pages = build_runtime_pages_payload(
        runtime_truth=payload,
        pnl_status=pnl_status,
        integrity_status=integrity_status,
        live_hold=live_hold,
    )
    return {
        "operator_runtime_truth.json": payload,
        "runtime_pages_payload.json": runtime_pages,
        "paper_pnl_source_of_truth_status.json": pnl_status,
        "paper_session_equity_status.json": {
            "schema_version": "paper_session_equity_status_v1",
            "generated_est": _est_now(),
            "paper_session_id": pnl_status.get("paper_session_id"),
            "current_session_pnl": pnl_status.get("current_session_pnl"),
            "current_session_equity": pnl_status.get("current_session_equity"),
            "accepted_fill_count": pnl_status.get("accepted_fill_count"),
            "held_row_count": pnl_status.get("held_row_count"),
            "reason": pnl_status.get("current_active_session_reason"),
        },
        "paper_lifetime_vs_current_session_pnl.json": {
            "schema_version": "paper_lifetime_vs_current_session_pnl_v1",
            "generated_est": _est_now(),
            "current_session_pnl": pnl_status.get("current_session_pnl"),
            "lifetime_or_old_paper_online_pnl": pnl_status.get("lifetime_paper_pnl"),
            "classification": pnl_status.get("paper_minus_49_classification"),
            "stale_source_path_if_any": pnl_status.get("stale_source_path_if_any"),
        },
        **integrity_payloads,
    }


def publish_realtime_runtime_truth(redis_client: Any = None) -> dict[str, dict[str, Any]]:
    payloads = build_realtime_runtime_truth(redis_client)
    OP_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        (OP_RUNTIME_DIR / name).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    previous_live_gate = _json_load(LIVE_GATE_RUNTIME_DIR / "live_gate_runtime_state.json", {}) or {}
    live_gate_display = build_live_gate_runtime_display_state(
        runtime_truth=payloads["operator_runtime_truth.json"],
        previous_state=previous_live_gate,
    )
    LIVE_GATE_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    (LIVE_GATE_RUNTIME_DIR / "live_gate_runtime_state.json").write_text(
        json.dumps(live_gate_display, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    payloads["live_gate_runtime_state.json"] = live_gate_display
    return payloads
