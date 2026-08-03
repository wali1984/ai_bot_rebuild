"""V2 live-gate runtime execution state.

This module writes and reads only V2-owned runtime state. It does not hold an
exchange client and does not submit, cancel, modify, or probe orders.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

LIVE_GATE_ENABLED = "enabled_operator_approved"
LIVE_GATE_BLOCKED = "blocked_human_only"
ALLOWED_ACTIVE_RISK_PROFILE_NAMES = frozenset({"conservative", "conservative_min_executable"})

KEY_LIVE_GATE_STATE = "v2:live_gate:state"
KEY_TRADER_EXECUTION_STATE = "v2:trader:execution_state"
KEY_TRADER_ACCEPTED_LIVE_SYMBOLS = "v2:trader:accepted_live_symbols"
KEY_RISK_ACTIVE_PROFILE = "v2:risk:active_profile"
ALLOWED_RUNTIME_KEYS = frozenset(
    {
        KEY_LIVE_GATE_STATE,
        KEY_TRADER_EXECUTION_STATE,
        KEY_TRADER_ACCEPTED_LIVE_SYMBOLS,
        KEY_RISK_ACTIVE_PROFILE,
    }
)

RUNTIME_STATE_PUBLIC_REL = Path(
    "v2/frontend/public/operator_runtime/v2_live_gate_runtime/latest/live_gate_runtime_state.json"
)
RUNTIME_STATE_WORKLOG_REL = Path(
    "claude_worklog/final_readiness/v2_live_gate_runtime_execution_adapter_enablement/latest/live_gate_runtime_state.json"
)

_EST = ZoneInfo("America/New_York")
_REPO_ROOT_ENV = "V2_REPO_ROOT"
_REDIS_REQUIRED_ENV = "V2_LIVE_GATE_RUNTIME_REDIS_REQUIRED"
_REDIS_DISABLED_ENV = "V2_LIVE_GATE_RUNTIME_DISABLE_REDIS_WRITES"
_RELEASE_MODE_ENV = "V2_RELEASE_MODE"
_MAX_STATE_AGE_SECONDS = 3600
RELEASE_MODE_NON_LIVE = "NON_LIVE"
RELEASE_MODE_LIVE_CANARY_APPROVED = "LIVE_CANARY_APPROVED"


def _repo_root(repo_root: Path | None = None) -> Path:
    if repo_root is not None:
        return repo_root.resolve()
    return Path(os.environ.get(_REPO_ROOT_ENV, "/home/wali/Desktop/AI BOT REBUILD")).resolve()


def _est_now() -> str:
    return datetime.now(tz=_EST).isoformat(timespec="seconds")


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def _json_load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _connect_redis() -> Any:
    try:
        import redis  # type: ignore

        client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        client.ping()
        return client
    except Exception:
        return None


def _redis_required() -> bool:
    return os.environ.get(_REDIS_REQUIRED_ENV, "1").strip().lower() not in {"0", "false", "no", "off"}


def _redis_disabled() -> bool:
    return os.environ.get(_REDIS_DISABLED_ENV, "0").strip().lower() in {"1", "true", "yes", "on"}


def current_release_mode() -> str:
    raw = os.environ.get(_RELEASE_MODE_ENV, RELEASE_MODE_NON_LIVE)
    return str(raw).strip() or RELEASE_MODE_NON_LIVE


def live_submit_release_mode_approved(release_mode: Any | None = None) -> bool:
    value = release_mode if release_mode not in (None, "") else current_release_mode()
    return str(value).strip().upper() == RELEASE_MODE_LIVE_CANARY_APPROVED


def payload_arms_live_submit(payload: Mapping[str, Any]) -> bool:
    return (
        payload.get("live_gate") == LIVE_GATE_ENABLED
        or payload.get("order_transport_submit_enabled") is True
        or payload.get("live_trading_enabled") is True
    )


def disarm_runtime_execution_state_payload(
    payload: Mapping[str, Any],
    *,
    reason: str,
    updated_by: str,
    generated_est: str | None = None,
    release_mode: Any | None = None,
) -> dict[str, Any]:
    refreshed_at = generated_est or _est_now()
    release_mode_value = str(release_mode if release_mode not in (None, "") else current_release_mode())
    out = dict(payload)
    out.update(
        {
            "generated_est": refreshed_at,
            "runtime_refreshed_at_est": refreshed_at,
            "live_gate": LIVE_GATE_BLOCKED,
            "trader_execution_enabled": False,
            "live_symbols": [],
            "execution_live_symbols": [],
            "order_transport_submit_enabled": False,
            "order_transport_submit_source": updated_by,
            "live_trading_enabled": False,
            "live_blocked": True,
            "operator_approved": False,
            "operator_approval_required": True,
            "places_real_order": False,
            "exchange_action_taken": False,
            "updated_by": updated_by,
            "reason": reason,
            "release_mode": release_mode_value,
        }
    )
    return out


def _safe_redis_set(redis_client: Any, key: str, payload: Any) -> tuple[bool, str | None]:
    if key not in ALLOWED_RUNTIME_KEYS or not key.startswith("v2:"):
        return False, "REDIS_KEY_NOT_ALLOWED"
    if redis_client is None:
        return False, "REDIS_UNAVAILABLE"
    try:
        redis_client.set(key, json.dumps(payload, sort_keys=True, default=str))
        return True, None
    except Exception as exc:
        return False, type(exc).__name__


def _runtime_state_paths(repo_root: Path) -> tuple[Path, Path]:
    return repo_root / RUNTIME_STATE_PUBLIC_REL, repo_root / RUNTIME_STATE_WORKLOG_REL


def build_runtime_execution_state_payload(
    *,
    accepted_symbols: list[str],
    risk_record: Mapping[str, Any],
    symbol_record: Mapping[str, Any],
    final_record: Mapping[str, Any],
    enable_audit_id: str,
    enabled_by: str,
    source_payload_ids: list[str],
    generated_est: str | None = None,
) -> dict[str, Any]:
    refreshed_at = generated_est or _est_now()
    release_mode = current_release_mode()
    profile_fields = risk_record.get("accepted_profile_fields")
    if not isinstance(profile_fields, Mapping):
        profile_fields = {}
    symbols = [str(symbol).upper() for symbol in accepted_symbols if str(symbol).strip()]
    payload = {
        "schema_version": "v2_live_gate_runtime_execution_state_v1",
        "generated_est": refreshed_at,
        "runtime_refreshed_at_est": refreshed_at,
        "enabled_at_est": refreshed_at,
        "enabled_by": enabled_by,
        "source": "v2.backend.app.services.live_gate.runtime_execution_state",
        "live_gate": LIVE_GATE_ENABLED,
        "trader_execution_enabled": True,
        "live_trading_enabled": True,
        "live_blocked": False,
        "operator_approved": True,
        "operator_approval_required": False,
        "live_symbols": symbols,
        "execution_live_symbols": symbols,
        "accepted_live_symbols": symbols,
        "accepted_symbols_audit_id": symbol_record.get("audit_id"),
        "accepted_risk_audit_id": risk_record.get("audit_id"),
        "final_approval_audit_id": final_record.get("audit_id"),
        "enable_audit_id": enable_audit_id,
        "risk_profile": {
            "profile_id": risk_record.get("accepted_profile_id"),
            "profile_name": risk_record.get("accepted_profile_name"),
            "fields": dict(profile_fields),
        },
        "source_payload_ids": [str(item) for item in source_payload_ids if str(item)],
        "kill_switch_enabled": True,
        "kill_switch_active": False,
        "kill_switch_conditions": list(profile_fields.get("kill_switch_conditions") or []),
        "max_leverage": profile_fields.get("max_leverage"),
        "margin_mutation_allowed": False,
        "leverage_mutation_allowed": False,
        "old_redis_write_allowed": False,
        "redis_trim_allowed": False,
        "legacy_restart_allowed": False,
        "order_lineage_required": [
            "prediction_id",
            "risk_decision_id",
            "orchestrator_decision_id",
            "signal_id",
            "live_gate_audit_id",
            "risk_profile_audit_id",
            "symbols_audit_id",
        ],
        "order_transport_write_guard_enabled": True,
        "order_transport_write_guard_source": "audited_live_gate_runtime_state",
        "order_transport_submit_enabled": True,
        "order_transport_submit_source": "audited_live_gate_runtime_state",
        "places_real_order": False,
        "exchange_action_taken": False,
        "release_mode": release_mode,
        "allowed_runtime_keys": sorted(ALLOWED_RUNTIME_KEYS),
    }
    if not live_submit_release_mode_approved(release_mode):
        return disarm_runtime_execution_state_payload(
            payload,
            reason="release_mode_not_live_canary_approved",
            updated_by="runtime_execution_state_writer",
            generated_est=refreshed_at,
            release_mode=release_mode,
        )
    return payload


def write_runtime_execution_state(
    *,
    repo_root: Path | None = None,
    accepted_symbols: list[str],
    risk_record: Mapping[str, Any],
    symbol_record: Mapping[str, Any],
    final_record: Mapping[str, Any],
    enable_audit_id: str,
    enabled_by: str,
    source_payload_ids: list[str],
    redis_client: Any | None = None,
) -> dict[str, Any]:
    root = _repo_root(repo_root)
    payload = build_runtime_execution_state_payload(
        accepted_symbols=accepted_symbols,
        risk_record=risk_record,
        symbol_record=symbol_record,
        final_record=final_record,
        enable_audit_id=enable_audit_id,
        enabled_by=enabled_by,
        source_payload_ids=source_payload_ids,
    )
    client = redis_client if redis_client is not None else (None if _redis_disabled() else _connect_redis())
    redis_writes: dict[str, dict[str, Any]] = {}
    values = {
        KEY_LIVE_GATE_STATE: payload,
        KEY_TRADER_EXECUTION_STATE: payload,
        KEY_TRADER_ACCEPTED_LIVE_SYMBOLS: payload["accepted_live_symbols"],
        KEY_RISK_ACTIVE_PROFILE: payload["risk_profile"],
    }
    for key, value in values.items():
        ok, error = _safe_redis_set(client, key, value)
        redis_writes[key] = {"ok": ok, "error": error}

    public_path, worklog_path = _runtime_state_paths(root)
    file_errors: list[str] = []
    for path in (public_path, worklog_path):
        try:
            _write_json_atomic(path, payload)
        except Exception as exc:
            file_errors.append(f"{path}:{type(exc).__name__}")

    redis_ok = all(row["ok"] is True for row in redis_writes.values())
    file_ok = not file_errors
    ok = file_ok and (redis_ok or not _redis_required())
    return {
        "ok": ok,
        "schema_version": "v2_live_gate_runtime_state_write_result_v1",
        "generated_est": _est_now(),
        "payload": payload,
        "redis_required": _redis_required(),
        "redis_disabled": _redis_disabled(),
        "redis_writes": redis_writes,
        "file_writes": {
            "public_path": str(public_path),
            "worklog_path": str(worklog_path),
            "ok": file_ok,
            "errors": file_errors,
        },
        "allowed_runtime_keys": sorted(ALLOWED_RUNTIME_KEYS),
        "old_redis_write_attempted": False,
        "exchange_mutation_attempted": False,
        "leverage_margin_mutation_attempted": False,
    }


def read_runtime_execution_state(
    *,
    repo_root: Path | None = None,
    redis_client: Any | None = None,
    max_age_seconds: int = _MAX_STATE_AGE_SECONDS,
) -> dict[str, Any]:
    root = _repo_root(repo_root)
    client = redis_client if redis_client is not None else (None if _redis_disabled() else _connect_redis())
    source = "missing"
    payload: dict[str, Any] = {}
    if client is not None:
        try:
            raw = client.get(KEY_LIVE_GATE_STATE)
            if raw:
                data = json.loads(raw)
                if isinstance(data, dict):
                    payload = data
                    source = KEY_LIVE_GATE_STATE
        except Exception:
            payload = {}
    if not payload:
        public_path, _worklog_path = _runtime_state_paths(root)
        payload = _json_load(public_path)
        source = str(public_path) if payload else "missing"
    validation = validate_runtime_execution_state(payload, max_age_seconds=max_age_seconds)
    return {
        "source": source,
        "payload": payload,
        "validation": validation,
        "loaded": bool(payload),
    }


def refresh_runtime_execution_state_heartbeat(
    *,
    repo_root: Path | None = None,
    redis_client: Any | None = None,
) -> dict[str, Any]:
    """Refresh V2 runtime-state freshness without changing approval lineage."""
    root = _repo_root(repo_root)
    current = read_runtime_execution_state(
        repo_root=root,
        redis_client=redis_client,
        max_age_seconds=10**9,
    )
    payload = current.get("payload") if isinstance(current.get("payload"), Mapping) else {}
    validation = current.get("validation") if isinstance(current.get("validation"), Mapping) else {}
    structural_blockers = [
        str(blocker)
        for blocker in validation.get("blockers") or []
        if str(blocker) != "LIVE_GATE_RUNTIME_STATE_STALE"
    ]
    if not payload or structural_blockers:
        return {
            "ok": False,
            "schema_version": "v2_live_gate_runtime_heartbeat_status_v1",
            "generated_est": _est_now(),
            "status": "LIVE_GATE_RUNTIME_HEARTBEAT_BLOCKED",
            "source": current.get("source"),
            "blockers": structural_blockers or ["LIVE_GATE_RUNTIME_STATE_MISSING"],
            "old_redis_write_attempted": False,
            "exchange_mutation_attempted": False,
            "leverage_margin_mutation_attempted": False,
        }

    refreshed = dict(payload)
    refreshed_at = _est_now()
    refreshed["generated_est"] = refreshed_at
    refreshed["runtime_refreshed_at_est"] = refreshed_at
    refreshed["runtime_heartbeat_source"] = "audited_live_gate_runtime_state_refresh"
    refreshed["enabled_at_est"] = payload.get("enabled_at_est")

    client = redis_client if redis_client is not None else (None if _redis_disabled() else _connect_redis())
    redis_writes: dict[str, dict[str, Any]] = {}
    values = {
        KEY_LIVE_GATE_STATE: refreshed,
        KEY_TRADER_EXECUTION_STATE: refreshed,
        KEY_TRADER_ACCEPTED_LIVE_SYMBOLS: refreshed.get("accepted_live_symbols") or [],
        KEY_RISK_ACTIVE_PROFILE: refreshed.get("risk_profile") or {},
    }
    for key, value in values.items():
        ok, error = _safe_redis_set(client, key, value)
        redis_writes[key] = {"ok": ok, "error": error}

    public_path, worklog_path = _runtime_state_paths(root)
    file_errors: list[str] = []
    for path in (public_path, worklog_path):
        try:
            _write_json_atomic(path, refreshed)
        except Exception as exc:
            file_errors.append(f"{path}:{type(exc).__name__}")

    redis_ok = all(row["ok"] is True for row in redis_writes.values())
    file_ok = not file_errors
    ok = file_ok and (redis_ok or not _redis_required())
    return {
        "ok": ok,
        "schema_version": "v2_live_gate_runtime_heartbeat_status_v1",
        "generated_est": refreshed_at,
        "status": "LIVE_GATE_RUNTIME_HEARTBEAT_REFRESHED" if ok else "LIVE_GATE_RUNTIME_HEARTBEAT_WRITE_FAILED",
        "source": current.get("source"),
        "runtime_refreshed_at_est": refreshed_at,
        "enabled_at_est": refreshed.get("enabled_at_est"),
        "redis_required": _redis_required(),
        "redis_disabled": _redis_disabled(),
        "redis_writes": redis_writes,
        "file_writes": {
            "public_path": str(public_path),
            "worklog_path": str(worklog_path),
            "ok": file_ok,
            "errors": file_errors,
        },
        "allowed_runtime_keys": sorted(ALLOWED_RUNTIME_KEYS),
        "old_redis_write_attempted": False,
        "exchange_mutation_attempted": False,
        "leverage_margin_mutation_attempted": False,
    }


def _age_seconds(payload: Mapping[str, Any]) -> float | None:
    generated = payload.get("runtime_refreshed_at_est") or payload.get("generated_est") or payload.get("enabled_at_est")
    if not isinstance(generated, str) or not generated:
        return None
    try:
        dt = datetime.fromisoformat(generated)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_EST)
        return max(0.0, (datetime.now(tz=_EST) - dt.astimezone(_EST)).total_seconds())
    except Exception:
        return None


def validate_runtime_execution_state(
    payload: Mapping[str, Any],
    *,
    max_age_seconds: int = _MAX_STATE_AGE_SECONDS,
) -> dict[str, Any]:
    blockers: list[str] = []
    if not payload:
        blockers.append("LIVE_GATE_RUNTIME_STATE_MISSING")
    symbols = [str(symbol) for symbol in payload.get("accepted_live_symbols") or []]
    live_symbols = [str(symbol) for symbol in payload.get("live_symbols") or []]
    execution_symbols = [str(symbol) for symbol in payload.get("execution_live_symbols") or []]
    risk_profile = payload.get("risk_profile") if isinstance(payload.get("risk_profile"), Mapping) else {}
    fields = risk_profile.get("fields") if isinstance(risk_profile.get("fields"), Mapping) else {}
    age = _age_seconds(payload)
    release_mode = payload.get("release_mode")
    if payload_arms_live_submit(payload) and not live_submit_release_mode_approved(release_mode):
        blockers.append("LIVE_SUBMIT_RELEASE_MODE_NOT_APPROVED")
    if payload.get("live_gate") != LIVE_GATE_ENABLED:
        blockers.append("LIVE_GATE_NOT_ENABLED")
    if payload.get("trader_execution_enabled") is not True:
        blockers.append("TRADER_EXECUTION_ENABLED_NOT_TRUE")
    if not symbols:
        blockers.append("ACCEPTED_LIVE_SYMBOLS_EMPTY")
    if symbols != live_symbols or symbols != execution_symbols:
        blockers.append("LIVE_SYMBOL_SETS_DO_NOT_MATCH_ACCEPTED_SYMBOLS")
    if not payload.get("accepted_risk_audit_id"):
        blockers.append("ACCEPTED_RISK_AUDIT_ID_MISSING")
    if not payload.get("accepted_symbols_audit_id"):
        blockers.append("ACCEPTED_SYMBOLS_AUDIT_ID_MISSING")
    if not payload.get("final_approval_audit_id"):
        blockers.append("FINAL_APPROVAL_AUDIT_ID_MISSING")
    if not payload.get("enable_audit_id"):
        blockers.append("ENABLE_AUDIT_ID_MISSING")
    if risk_profile.get("profile_name") not in ALLOWED_ACTIVE_RISK_PROFILE_NAMES:
        blockers.append("ACTIVE_RISK_PROFILE_NOT_APPROVED_CONSERVATIVE_FAMILY")
    if fields.get("max_leverage") != 1.0:
        blockers.append("ACTIVE_RISK_PROFILE_MAX_LEVERAGE_NOT_ONE")
    if payload.get("margin_mutation_allowed") is not False:
        blockers.append("MARGIN_MUTATION_NOT_DISABLED")
    if payload.get("leverage_mutation_allowed") is not False:
        blockers.append("LEVERAGE_MUTATION_NOT_DISABLED")
    if payload.get("kill_switch_active") is True:
        blockers.append("KILL_SWITCH_ACTIVE")
    if payload.get("order_transport_write_guard_enabled") is not True:
        blockers.append("ORDER_TRANSPORT_WRITE_GUARD_NOT_ENABLED")
    if payload.get("order_transport_submit_enabled") is not True:
        blockers.append("ORDER_TRANSPORT_SUBMIT_NOT_ENABLED")
    if age is None:
        blockers.append("LIVE_GATE_RUNTIME_STATE_TIMESTAMP_MISSING")
    elif age > max_age_seconds:
        blockers.append("LIVE_GATE_RUNTIME_STATE_STALE")
    return {
        "valid": not blockers,
        "blockers": blockers,
        "age_seconds": age,
        "max_age_seconds": max_age_seconds,
    }


def validate_order_lineage_candidate(
    *,
    runtime_state: Mapping[str, Any],
    symbol: str,
    prediction_id: Any,
    risk_decision_id: Any,
    orchestrator_decision_id: Any,
    signal_id: Any = None,
    live_gate_audit_id: Any = None,
    risk_profile_audit_id: Any = None,
    symbols_audit_id: Any = None,
) -> dict[str, Any]:
    validation = validate_runtime_execution_state(runtime_state)
    blockers = list(validation.get("blockers") or [])
    accepted = {str(item) for item in runtime_state.get("accepted_live_symbols") or []}
    if str(symbol) not in accepted:
        blockers.append("SYMBOL_NOT_ACCEPTED_FOR_LIVE_EXECUTION")
    if not prediction_id:
        blockers.append("PREDICTION_ID_MISSING")
    if not risk_decision_id:
        blockers.append("RISK_DECISION_ID_MISSING")
    if not orchestrator_decision_id:
        blockers.append("ORCHESTRATOR_DECISION_ID_MISSING")
    if signal_id is not None and not signal_id:
        blockers.append("SIGNAL_ID_MISSING")
    if live_gate_audit_id is not None and not live_gate_audit_id:
        blockers.append("LIVE_GATE_AUDIT_ID_MISSING")
    if risk_profile_audit_id is not None and not risk_profile_audit_id:
        blockers.append("RISK_PROFILE_AUDIT_ID_MISSING")
    if symbols_audit_id is not None and not symbols_audit_id:
        blockers.append("SYMBOLS_AUDIT_ID_MISSING")
    return {"allowed": not blockers, "blockers": blockers}


def apply_runtime_state_to_trader_status(
    trader_status: Mapping[str, Any],
    runtime_read: Mapping[str, Any],
) -> dict[str, Any]:
    out = dict(trader_status)
    payload = runtime_read.get("payload") if isinstance(runtime_read.get("payload"), Mapping) else {}
    validation = runtime_read.get("validation") if isinstance(runtime_read.get("validation"), Mapping) else {}
    enabled = bool(validation.get("valid"))
    live_symbols = list(payload.get("live_symbols") or []) if enabled else []
    execution_symbols = list(payload.get("execution_live_symbols") or []) if enabled else []
    out["live_gate_runtime_state"] = {
        "loaded": bool(runtime_read.get("loaded")),
        "source": runtime_read.get("source"),
        "validation": dict(validation),
        "accepted_symbols_audit_id": payload.get("accepted_symbols_audit_id"),
        "accepted_risk_audit_id": payload.get("accepted_risk_audit_id"),
        "final_approval_audit_id": payload.get("final_approval_audit_id"),
        "enable_audit_id": payload.get("enable_audit_id"),
        "risk_profile": payload.get("risk_profile"),
        "kill_switch_enabled": payload.get("kill_switch_enabled"),
        "kill_switch_active": payload.get("kill_switch_active"),
    }
    out["trader_execution_enabled"] = enabled
    out["live_gate"] = payload.get("live_gate") if enabled else LIVE_GATE_BLOCKED
    out["live_gate_status"] = out["live_gate"]
    out["live_symbols"] = live_symbols
    out["execution_live_symbols"] = execution_symbols
    out["status"] = "TRADER_CONNECTED_EXECUTION_ENABLED" if enabled else "TRADER_CONNECTED_EXECUTION_FROZEN"
    out["classification"] = out["status"]
    out["exchange_mutation_state"] = (
        "EXCHANGE_MUTATION_ALLOWED_BY_AUDITED_LIVE_GATE" if enabled else "EXCHANGE_MUTATION_FROZEN"
    )
    out["account_mode"] = "binance_private_live_gated" if enabled else out.get("account_mode", "execution_frozen_shadow")
    out["live_order_transport_bound"] = False
    out["places_real_order"] = False
    out["writes_exchange_orders"] = False
    out["leverage_changed"] = False
    out["margin_mode_changed"] = False
    rows = []
    for row in out.get("runtime_observation_rows") or []:
        if not isinstance(row, Mapping):
            continue
        check = validate_order_lineage_candidate(
            runtime_state=payload,
            symbol=str(row.get("symbol") or ""),
            prediction_id=row.get("prediction_id"),
            risk_decision_id=row.get("risk_decision_id"),
            orchestrator_decision_id=row.get("orchestrator_decision_id"),
            signal_id=row.get("signal_id"),
        )
        merged = dict(row)
        merged["symbol_accepted_for_live"] = str(row.get("symbol") or "") in set(execution_symbols)
        merged["lineage_complete_for_live"] = not any(
            item in check["blockers"]
            for item in (
                "PREDICTION_ID_MISSING",
                "RISK_DECISION_ID_MISSING",
                "ORCHESTRATOR_DECISION_ID_MISSING",
                "SIGNAL_ID_MISSING",
            )
        )
        merged["eligible_for_live_execution"] = enabled and check["allowed"]
        merged["live_execution_blockers"] = check["blockers"]
        merged["places_real_order"] = False
        rows.append(merged)
    out["runtime_observation_rows"] = rows
    out["runtime_observation_sample"] = rows[:32]
    return out


def get_canonical_live_gate_status(
    *,
    redis_client: Any | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Single source of truth for live-gate status consumed by all V2 surfaces.

    Always returns ``blocked_human_only`` unless BOTH conditions hold:
    1. ``V2_RELEASE_MODE=LIVE_CANARY_APPROVED`` env var is set, AND
    2. The full operator approval flow has written a valid runtime state.

    Call this instead of reading Redis/files directly so that every
    frontend/backend surface agrees on the gate value.
    """
    release_mode = current_release_mode()
    if not live_submit_release_mode_approved(release_mode):
        return {
            "live_gate": LIVE_GATE_BLOCKED,
            "live_trading_enabled": False,
            "live_blocked": True,
            "operator_approved": False,
            "live_symbols": [],
            "execution_live_symbols": [],
            "release_mode": release_mode,
            "source": "canonical_live_gate_status_release_mode_guard",
            "conflict_check": "no_conflict_release_mode_blocked",
        }
    runtime = read_runtime_execution_state(redis_client=redis_client, repo_root=repo_root)
    payload = runtime.get("payload") or {}
    validation = runtime.get("validation") or {}
    if not validation.get("valid") or payload.get("live_gate") != LIVE_GATE_ENABLED:
        return {
            "live_gate": LIVE_GATE_BLOCKED,
            "live_trading_enabled": False,
            "live_blocked": True,
            "operator_approved": False,
            "live_symbols": [],
            "execution_live_symbols": [],
            "release_mode": release_mode,
            "source": runtime.get("source", "missing"),
            "conflict_check": "no_conflict_runtime_not_approved",
        }
    return {
        "live_gate": LIVE_GATE_ENABLED,
        "live_trading_enabled": True,
        "live_blocked": False,
        "operator_approved": True,
        "live_symbols": list(payload.get("live_symbols") or []),
        "execution_live_symbols": list(payload.get("execution_live_symbols") or []),
        "release_mode": release_mode,
        "source": runtime.get("source", "missing"),
        "conflict_check": "no_conflict_operator_approved",
    }
