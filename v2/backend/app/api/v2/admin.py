"""Admin aggregation endpoints for the NERVYX OPS TERMINAL.

These endpoints compose data from existing Redis keys, services, and internal
calls to produce the payloads consumed by admin portal pages.

Safety boundaries (CLAUDE.md):
- Read-only. No exchange orders, no leverage/margin changes.
- No legacy Redis key writes.
- Does not restart or mutate any live runtime.
- Does not import trainer modules into FastAPI process.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

from app.api.v2._common import get_redis
from app.auth.security import require_admin, require_auth
from app.auth.users import UserRecord, get_user_store
from app.services.pipeline_control.service import build_pipeline_status

router = APIRouter(prefix="/admin", tags=["v2-admin-aggregation"])

_REQUIRE_ADMIN = require_admin
_REQUIRE_OPERATOR = require_admin


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _redis_read(key: str) -> Any:
    client = get_redis()
    if client is None:
        return None
    try:
        raw = client.get(key)
    except Exception:
        return None
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(str(raw))
    except (TypeError, ValueError):
        return None


def _redis_list(key: str) -> list[dict[str, Any]]:
    value = _redis_read(key)
    if value is None:
        return []
    if isinstance(value, list):
        result: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                result.append(item)
            elif isinstance(item, (str, bytes)):
                try:
                    parsed = json.loads(item)
                    if isinstance(parsed, dict):
                        result.append(parsed)
                except Exception:
                    pass
        return result
    if isinstance(value, dict):
        return [value]
    return []


def _safe_str(value: Any, fallback: str = "unknown") -> str:
    return str(value) if value is not None else fallback


def _safe_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


# ---------------------------------------------------------------------------
# /api/v2/admin/overview  — aggregated health snapshot for Overview page
# ---------------------------------------------------------------------------

@router.get("/overview")
async def get_admin_overview(_: UserRecord = Depends(_REQUIRE_ADMIN)) -> dict[str, Any]:
    now = _utc_now()

    # ── Trainer — read from prediction key (summary key is rarely set) ───────
    trainer_raw = _redis_read("v2:trainer:summary")
    if not isinstance(trainer_raw, dict):
        trainer_raw = _redis_read("v2:prediction:BTCUSDT:1h") or {}
    trainer_state = "unknown"
    trainer_checkpoint = None
    trainer_cuda = False
    trainer_coverage: float | None = None
    if isinstance(trainer_raw, dict):
        trainer_state = _safe_str(trainer_raw.get("state") or ("ACTIVE_REDIS_EVIDENCE" if trainer_raw.get("checkpoint_id") else None), "unknown")
        trainer_checkpoint = trainer_raw.get("checkpoint_id")
        trainer_cuda = bool(trainer_raw.get("cuda_active"))
        trainer_coverage = trainer_raw.get("data_coverage") or trainer_raw.get("data_coverage_percent")

    # ── Risk gateway ─────────────────────────────────────────────────────────
    risk_heartbeat = _redis_read("v2:risk:gateway:heartbeat")
    risk_profile = _redis_read("v2:risk:active_profile")
    risk_latest = _redis_read("v2:risk:gateway:latest")
    live_blocked = True
    risk_profile_name = "unknown"
    risk_decisions_total = 0
    risk_last_at = None
    if isinstance(risk_heartbeat, dict):
        risk_decisions_total = _safe_int(risk_heartbeat.get("decisions_processed_total"))
        risk_last_at = risk_heartbeat.get("finished_at") or risk_heartbeat.get("started_at")
        live_blocked = risk_heartbeat.get("live_blocked", True)
    if isinstance(risk_profile, dict):
        risk_profile_name = _safe_str(risk_profile.get("profile_name") or risk_profile.get("profile_id"), "unknown")
    if isinstance(risk_latest, dict):
        live_blocked = bool(risk_latest.get("live_blocked", True))

    # ── Orchestrator ─────────────────────────────────────────────────────────
    orch_heartbeat = _redis_read("v2:orchestrator:heartbeat")
    orch_status = "unknown"
    orch_last_at = None
    orch_decisions = 0
    if isinstance(orch_heartbeat, dict):
        orch_status = "ok" if orch_heartbeat.get("status") in ("active", "running", "ok") else "warn"
        orch_last_at = orch_heartbeat.get("finished_at") or orch_heartbeat.get("timestamp")
        orch_decisions = _safe_int(orch_heartbeat.get("decisions_total"))

    # ── Pipeline ─────────────────────────────────────────────────────────────
    try:
        pipeline = build_pipeline_status(get_redis())
        live_gate = _safe_str(pipeline.get("live_gate"), "unknown")
        symbol_count = len(pipeline.get("symbols") or [])
        allowed_run_types = pipeline.get("allowed_run_types") or []
    except Exception:
        live_gate = "unknown"
        symbol_count = 0
        allowed_run_types = []

    # ── Assemble services list ────────────────────────────────────────────────
    trainer_svc_status = (
        "ok" if trainer_state in ("ACTIVE_REDIS_EVIDENCE", "ACTIVE") else
        "warn" if trainer_state == "MISSING_EVIDENCE" else "unknown"
    )
    risk_svc_status = "ok" if risk_last_at else "unknown"
    orch_svc_status = orch_status if orch_status != "unknown" else "unknown"
    pipeline_svc_status = "ok" if live_gate != "unknown" else "unknown"

    services = [
        {
            "id": "trainer",
            "name": "Trainer / ML",
            "status": trainer_svc_status,
            "heartbeat_at": risk_last_at,
            "lag_ms": None,
            "error_count": 0,
            "warning_count": 0,
            "owner": "v2-trainer",
            "version": _safe_str(trainer_checkpoint, None) if trainer_checkpoint else None,
            "detail": trainer_state,
            "cuda_active": trainer_cuda,
            "data_coverage": trainer_coverage,
        },
        {
            "id": "risk-gateway",
            "name": "Risk Gateway",
            "status": risk_svc_status,
            "heartbeat_at": risk_last_at,
            "lag_ms": None,
            "error_count": 0,
            "warning_count": 0,
            "owner": "v2-risk",
            "version": None,
            "detail": risk_profile_name,
            "decisions_total": risk_decisions_total,
        },
        {
            "id": "orchestrator",
            "name": "Orchestrator",
            "status": orch_svc_status,
            "heartbeat_at": orch_last_at,
            "lag_ms": None,
            "error_count": 0,
            "warning_count": 0,
            "owner": "v2-orchestrator",
            "version": None,
            "detail": f"{orch_decisions} decisions",
        },
        {
            "id": "pipeline",
            "name": "Pipeline",
            "status": pipeline_svc_status,
            "heartbeat_at": None,
            "lag_ms": None,
            "error_count": 0,
            "warning_count": 0,
            "owner": "v2-pipeline",
            "version": None,
            "detail": live_gate,
            "symbol_count": symbol_count,
            "allowed_run_types": allowed_run_types,
        },
    ]

    # ── Portfolio summary from canonical Redis source ────────────────────────
    portfolio_state_raw = _redis_read("v2:portfolio:state")
    portfolio_summary: dict[str, Any] = {}
    if isinstance(portfolio_state_raw, dict):
        portfolio_summary = {
            "equity": portfolio_state_raw.get("equity"),
            "realized_pnl_usd": portfolio_state_raw.get("realized_pnl_usd"),
            "unrealized_pnl_usd": portfolio_state_raw.get("unrealized_pnl_usd"),
            "open_positions_count": portfolio_state_raw.get("open_positions_count"),
            "closed_positions_count": portfolio_state_raw.get("closed_positions_count"),
            "last_fill_utc": portfolio_state_raw.get("last_fill_utc"),
            "account_mode": portfolio_state_raw.get("account_mode"),
            "classification": portfolio_state_raw.get("classification"),
        }

    return {
        "generated_at": now,
        "live_gate": live_gate,
        "live_blocked": live_blocked,
        "services": services,
        "active_incidents": [],
        "data_health": "unknown",
        "intelligence_health": trainer_svc_status,
        "orchestration_health": orch_svc_status,
        "risk_status": "block" if live_blocked else "allow",
        "execution_status": "unknown",
        "exchange_status": "unknown",
        "trainer": {
            "state": trainer_state,
            "checkpoint_id": trainer_checkpoint,
            "cuda_active": trainer_cuda,
            "data_coverage": trainer_coverage,
        },
        "risk": {
            "profile_name": risk_profile_name,
            "live_blocked": live_blocked,
            "decisions_total": risk_decisions_total,
            "last_at": risk_last_at,
        },
        "pipeline": {
            "live_gate": live_gate,
            "symbol_count": symbol_count,
            "allowed_run_types": allowed_run_types,
        },
        "portfolio": portfolio_summary,
    }


# ---------------------------------------------------------------------------
# /api/v2/admin/users  — user list for Users page
# ---------------------------------------------------------------------------

@router.get("/users")
async def get_admin_users(_: UserRecord = Depends(_REQUIRE_ADMIN)) -> dict[str, Any]:
    now = _utc_now()
    try:
        store = get_user_store()
        users = store.list_users()
        user_list = []
        for u in users:
            user_list.append({
                "id": _safe_str(u.get("id"), ""),
                "email": _safe_str(u.get("email"), ""),
                "role": _safe_str(u.get("role"), "viewer"),
                "status": "active" if u.get("is_active", True) else "inactive",
                "created_at": u.get("created_at"),
                "last_login_at": u.get("last_login"),
                "session_count": 1,
            })
        return {
            "generated_at": now,
            "users": user_list,
            "total": len(user_list),
            "active_sessions": len([u for u in user_list if u["status"] == "active"]),
        }
    except Exception as exc:
        return {
            "generated_at": now,
            "users": [],
            "total": 0,
            "active_sessions": 0,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# /api/v2/admin/logs/recent  — recent events and errors
# ---------------------------------------------------------------------------

@router.get("/logs/recent")
async def get_admin_logs(_: UserRecord = Depends(_REQUIRE_OPERATOR)) -> dict[str, Any]:
    now = _utc_now()
    entries: list[dict[str, Any]] = []
    error_count_1h = 0
    warn_count_1h = 0

    # Read from backend errors log
    errors_log = Path(os.environ.get("V2_REPO_ROOT", "/home/wali/Desktop/AI BOT REBUILD")) / "v2" / "backend" / "logs" / "errors.jsonl"
    if errors_log.exists():
        try:
            lines = errors_log.read_text(errors="replace").splitlines()
            for line in lines[-50:]:
                try:
                    entry = json.loads(line)
                    level = _safe_str(entry.get("level", "error")).lower()
                    entries.append({
                        "id": _safe_str(entry.get("id") or entry.get("timestamp"), str(len(entries))),
                        "level": level,
                        "service": _safe_str(entry.get("service") or entry.get("logger"), "backend"),
                        "message": _safe_str(entry.get("message") or entry.get("msg"), ""),
                        "timestamp": _safe_str(entry.get("timestamp") or entry.get("time"), now),
                    })
                    if level == "error":
                        error_count_1h += 1
                    elif level in ("warn", "warning"):
                        warn_count_1h += 1
                except Exception:
                    pass
        except Exception:
            pass

    # Also scan Redis stream for recent events
    client = get_redis()
    if client is not None:
        try:
            redis_events = client.lrange("v2:admin:log:recent", 0, 19)
            for raw in (redis_events or []):
                try:
                    ev = json.loads(raw) if isinstance(raw, str) else raw
                    if isinstance(ev, dict):
                        entries.append({
                            "id": _safe_str(ev.get("id", str(len(entries)))),
                            "level": _safe_str(ev.get("level", "info")),
                            "service": _safe_str(ev.get("service", "system")),
                            "message": _safe_str(ev.get("message", "")),
                            "timestamp": _safe_str(ev.get("timestamp", now)),
                        })
                except Exception:
                    pass
        except Exception:
            pass

    # Synthesise a system event from trainer + risk state
    trainer_raw = _redis_read("v2:trainer:summary")
    if isinstance(trainer_raw, dict) and trainer_raw.get("state"):
        entries.insert(0, {
            "id": "sys-trainer-state",
            "level": "info",
            "service": "trainer",
            "message": f"Trainer state: {trainer_raw['state']} | model: {trainer_raw.get('model_id', '?')}",
            "timestamp": now,
        })

    risk_heartbeat = _redis_read("v2:risk:gateway:heartbeat")
    if isinstance(risk_heartbeat, dict):
        ts = risk_heartbeat.get("finished_at") or risk_heartbeat.get("started_at") or now
        total = _safe_int(risk_heartbeat.get("decisions_processed_total"))
        entries.insert(0, {
            "id": "sys-risk-heartbeat",
            "level": "info",
            "service": "risk-gateway",
            "message": f"Risk gateway heartbeat | decisions_total={total} | live_blocked={risk_heartbeat.get('live_blocked', True)}",
            "timestamp": ts,
        })

    return {
        "generated_at": now,
        "entries": entries[:60],
        "error_count_1h": error_count_1h,
        "warn_count_1h": warn_count_1h,
    }


# ---------------------------------------------------------------------------
# /api/v2/admin/execution/fills  — paper execution decisions
# ---------------------------------------------------------------------------

@router.get("/execution/fills")
async def get_admin_execution_fills(_: UserRecord = Depends(_REQUIRE_OPERATOR)) -> dict[str, Any]:
    now = _utc_now()
    decisions = _redis_list("v2:risk:decisions")
    risk_latest = _redis_read("v2:risk:gateway:latest")
    risk_heartbeat = _redis_read("v2:risk:gateway:heartbeat")

    fills = []
    if isinstance(risk_latest, dict):
        fills.append({
            "order_id": _safe_str(risk_latest.get("risk_decision_id"), "latest"),
            "symbol": _safe_str(risk_latest.get("symbol"), "?"),
            "side": _safe_str(risk_latest.get("side"), "?"),
            "action": _safe_str(risk_latest.get("risk_action"), "?").upper(),
            "result": _safe_str(risk_latest.get("risk_result"), "?"),
            "reason": _safe_str(risk_latest.get("risk_reason_code"), ""),
            "live_blocked": bool(risk_latest.get("live_blocked", True)),
            "timestamp": _safe_str(risk_latest.get("generated_at"), now),
            "confidence": risk_latest.get("strategy_router_confidence"),
        })

    for d in decisions[:19]:
        if not isinstance(d, dict):
            continue
        fills.append({
            "order_id": _safe_str(d.get("risk_decision_id") or d.get("id"), ""),
            "symbol": _safe_str(d.get("symbol"), "?"),
            "side": _safe_str(d.get("side"), "?"),
            "action": _safe_str(d.get("risk_action"), "?").upper(),
            "result": _safe_str(d.get("risk_result") or d.get("result"), "?"),
            "reason": _safe_str(d.get("risk_reason_code") or d.get("reason_code"), ""),
            "live_blocked": bool(d.get("live_blocked", True)),
            "timestamp": _safe_str(d.get("generated_at") or d.get("timestamp"), now),
            "confidence": d.get("strategy_router_confidence"),
        })

    orders_24h = len(fills)
    fills_count = len([f for f in fills if f["action"] in ("ALLOW", "FILL")])
    rejects = len([f for f in fills if f["action"] in ("DENY", "BLOCK", "REJECT")])

    mode = "paper"
    gate = "BLOCKED"
    if isinstance(risk_heartbeat, dict):
        gate = "BLOCKED" if risk_heartbeat.get("live_blocked", True) else "OPEN"

    return {
        "generated_at": now,
        "mode": mode,
        "gate": gate,
        "orders_24h": orders_24h,
        "fills_24h": fills_count,
        "rejects_24h": rejects,
        "avg_fill_latency_ms": None,
        "avg_slippage_pct": None,
        "fills": fills,
    }


# ---------------------------------------------------------------------------
# /api/v2/admin/exchanges/status  — exchange connectivity
# ---------------------------------------------------------------------------

@router.get("/exchanges/status")
async def get_admin_exchanges(_: UserRecord = Depends(_REQUIRE_OPERATOR)) -> dict[str, Any]:
    now = _utc_now()

    # Read from Redis market stream telemetry
    stream_raw = _redis_read("v2:market:stream:btcusdt:telemetry") or _redis_read("v2:market:stream:telemetry")
    stream_stale = True
    stream_lag_ms: int | None = None
    stream_last_at: str | None = None
    stream_source = "unknown"

    if isinstance(stream_raw, dict):
        stream_stale = bool(stream_raw.get("stale", True))
        stream_lag_ms = stream_raw.get("lag_ms")
        stream_last_at = stream_raw.get("last_frame_at")
        stream_source = _safe_str(stream_raw.get("source"), "unknown")

    exchanges = [
        {
            "id": "binance-usdm",
            "name": "Binance USD-M Futures",
            "status": "warn" if stream_stale else "ok",
            "connectivity": "rest_fallback" if stream_stale else "wss_primary",
            "credential_status": "credential_source_pending",
            "live_trading_enabled": False,
            "read_only": True,
            "last_frame_at": stream_last_at,
            "lag_ms": stream_lag_ms,
            "mode": "read_only",
            "account_type": "usd_m_futures",
            "stream_stale": stream_stale,
            "stream_source": stream_source,
        }
    ]

    return {
        "generated_at": now,
        "exchanges": exchanges,
        "total": len(exchanges),
        "connected": len([e for e in exchanges if e["status"] == "ok"]),
        "stream_stale": stream_stale,
        "stream_last_at": stream_last_at,
        "stream_lag_ms": stream_lag_ms,
    }


# ---------------------------------------------------------------------------
# /api/v2/admin/audit/chain  — audit chain summary
# ---------------------------------------------------------------------------

@router.get("/audit/chain")
async def get_admin_audit_chain(_: UserRecord = Depends(require_auth)) -> dict[str, Any]:
    now = _utc_now()

    entries: list[dict[str, Any]] = []
    chain_length = 0
    last_entry_at: str | None = None

    # Try Redis audit stream
    client = get_redis()
    if client is not None:
        try:
            raw_entries = client.lrange("audit:chain", 0, 49)
            for raw in (raw_entries or []):
                try:
                    entry = json.loads(raw) if isinstance(raw, str) else raw
                    if isinstance(entry, dict):
                        entries.append({
                            "audit_id": _safe_str(entry.get("audit_id") or entry.get("jti"), ""),
                            "actor": _safe_str(entry.get("actor") or entry.get("sub"), "system"),
                            "action": _safe_str(entry.get("action"), ""),
                            "result": _safe_str(entry.get("result"), "success"),
                            "timestamp": _safe_str(entry.get("timestamp") or entry.get("iat"), now),
                            "reason": entry.get("reason"),
                            "evidence": entry.get("evidence"),
                        })
                except Exception:
                    pass
            try:
                chain_length = _safe_int(client.llen("audit:chain"))
                last_entry_at = entries[0]["timestamp"] if entries else None
            except Exception:
                pass
        except Exception:
            pass

    return {
        "generated_at": now,
        "entries": entries,
        "chain_length": chain_length,
        "last_entry_at": last_entry_at,
    }
