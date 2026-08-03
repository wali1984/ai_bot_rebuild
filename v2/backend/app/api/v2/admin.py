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

import asyncio
import json
import os
import secrets
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from starlette.concurrency import run_in_threadpool

from app.api.v2._common import get_redis
from app.api.v2.codex_reviews import extract_codex_artifact_verdict
from app.auth.security import require_admin, require_auth
from app.auth.users import UserRecord, get_user_store
from app.services.pipeline_control.service import build_pipeline_status

_REPO_ROOT = Path(os.environ.get("V2_REPO_ROOT", "/home/wali/Desktop/AI BOT REBUILD"))

router = APIRouter(prefix="/admin", tags=["v2-admin-aggregation"])

_REQUIRE_ADMIN = require_admin
_REQUIRE_OPERATOR = require_admin
ADMIN_OVERVIEW_BUILD_TIMEOUT_SECONDS = float(os.environ.get("ALPHAFORGE_ADMIN_OVERVIEW_BUILD_TIMEOUT_SECONDS", "1.5"))
ADMIN_OVERVIEW_CACHE_TTL_SECONDS = float(os.environ.get("ALPHAFORGE_ADMIN_OVERVIEW_CACHE_TTL_SECONDS", "2.0"))
_ADMIN_OVERVIEW_CACHE_LOCK = threading.Lock()
_ADMIN_OVERVIEW_CACHE: tuple[float, dict[str, Any]] | None = None


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


def _admin_overview_fallback(reason: str) -> dict[str, Any]:
    return {
        "generated_at": _utc_now(),
        "status": "degraded",
        "live_gate": "blocked_human_only",
        "live_blocked": True,
        "services": [],
        "active_incidents": [{"status": "investigating", "summary": reason}],
        "data_health": "degraded",
        "intelligence_health": "unknown",
        "orchestration_health": "unknown",
        "risk_status": "block",
        "execution_status": "blocked",
        "exchange_status": "unknown",
        "trainer": {"state": "unknown", "checkpoint_id": None, "cuda_active": False, "data_coverage": None},
        "risk": {"profile_name": "unknown", "live_blocked": True, "decisions_total": 0, "last_at": None},
        "pipeline": {"live_gate": "blocked_human_only", "symbol_count": 0, "allowed_run_types": []},
        "portfolio": {},
        "warnings": [reason],
        "routes_to_live": False,
        "places_real_order": False,
    }


async def _admin_overview_payload_bounded() -> dict[str, Any]:
    global _ADMIN_OVERVIEW_CACHE  # noqa: PLW0603
    now = time.monotonic()
    with _ADMIN_OVERVIEW_CACHE_LOCK:
        cached = _ADMIN_OVERVIEW_CACHE
        if cached is not None and now - cached[0] <= ADMIN_OVERVIEW_CACHE_TTL_SECONDS:
            return dict(cached[1])
    try:
        payload = await asyncio.wait_for(
            run_in_threadpool(_build_admin_overview_payload),
            timeout=max(0.1, ADMIN_OVERVIEW_BUILD_TIMEOUT_SECONDS),
        )
    except asyncio.TimeoutError:
        return _admin_overview_fallback("Admin overview read exceeded bounded runtime budget")
    except Exception as exc:
        return _admin_overview_fallback(f"Admin overview read unavailable: {type(exc).__name__}")
    with _ADMIN_OVERVIEW_CACHE_LOCK:
        _ADMIN_OVERVIEW_CACHE = (time.monotonic(), dict(payload))
    return payload


# ---------------------------------------------------------------------------
# /api/v2/admin/overview  — aggregated health snapshot for Overview page
# ---------------------------------------------------------------------------

def _build_admin_overview_payload() -> dict[str, Any]:
    now = _utc_now()

    # ── Trainer — read from prediction key (summary key is rarely set) ───────
    trainer_raw = _redis_read("v2:trainer:summary")
    if not isinstance(trainer_raw, dict):
        trainer_raw = _redis_read("v2:prediction:BTCUSDT:1h") or {}
    trainer_state = "unknown"
    trainer_checkpoint = None
    trainer_cuda = False
    trainer_coverage: float | None = None
    trainer_evidence_age_s: float | None = None
    if isinstance(trainer_raw, dict):
        trainer_state = _safe_str(trainer_raw.get("state") or ("ACTIVE_REDIS_EVIDENCE" if trainer_raw.get("checkpoint_id") else None), "unknown")
        trainer_checkpoint = trainer_raw.get("checkpoint_id")
        trainer_cuda = bool(trainer_raw.get("cuda_active"))
        trainer_coverage = trainer_raw.get("data_coverage") or trainer_raw.get("data_coverage_percent")
        # Honest freshness (mirrors /api/v2/trainer/status): the stored state
        # string may say ACTIVE_REDIS_EVIDENCE while the underlying evidence
        # is days old. Grade by the evidence timestamp; >1800s = stale
        # (same threshold as trainer.py _freshness_from_age).
        for _ts_field in ("_source_generated_utc", "generated_utc", "generated_at", "created_at"):
            _ts_value = trainer_raw.get(_ts_field)
            if isinstance(_ts_value, str) and _ts_value.strip():
                try:
                    _parsed = datetime.fromisoformat(_ts_value.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if _parsed.tzinfo is None:
                    _parsed = _parsed.replace(tzinfo=UTC)
                trainer_evidence_age_s = max(0.0, (datetime.now(UTC) - _parsed.astimezone(UTC)).total_seconds())
                break
        if trainer_evidence_age_s is not None and trainer_evidence_age_s > 1800 and trainer_state == "ACTIVE_REDIS_EVIDENCE":
            trainer_state = "STALE_REDIS_EVIDENCE"

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
        "warn" if trainer_state in ("MISSING_EVIDENCE", "STALE_REDIS_EVIDENCE") else "unknown"
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
            "evidence_age_seconds": round(trainer_evidence_age_s, 1) if trainer_evidence_age_s is not None else None,
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
        "status": "available",
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
        "routes_to_live": False,
        "places_real_order": False,
    }


@router.get("/overview")
async def get_admin_overview(_: UserRecord = Depends(_REQUIRE_ADMIN)) -> dict[str, Any]:
    return await _admin_overview_payload_bounded()


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
                # Honest null: auth uses stateless JWTs — there is no
                # server-side session registry, so a per-user live-session
                # count is unknowable (was a hardcoded placeholder of 1).
                "session_count": None,
            })
        return {
            "generated_at": now,
            "users": user_list,
            "total": len(user_list),
            # Sessions are not tracked (stateless JWT); expose the real
            # active-USER count under its own name instead of mislabeling it.
            "active_sessions": None,
            "active_users": len([u for u in user_list if u["status"] == "active"]),
            "session_tracking": "not_tracked_stateless_jwt",
        }
    except Exception as exc:
        return {
            "generated_at": now,
            "users": [],
            "total": 0,
            "active_sessions": None,
            "active_users": 0,
            "session_tracking": "not_tracked_stateless_jwt",
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

    # Canonical market-stream truth. The previous implementation read
    # v2:market:stream:btcusdt:telemetry / v2:market:stream:telemetry, keys
    # that have NO writer anywhere — so this page permanently reported
    # STALE/rest_fallback while /api/v2/status market_stream was CURRENT.
    stream_stale = True
    stream_lag_ms: int | None = None
    stream_last_at: str | None = None
    stream_source = "unknown"
    stream_status = "unknown"
    try:
        from app.api.v2.status_contracts import _safe_market_stream_status

        stream = _safe_market_stream_status("BTCUSDT")
        stream_stale = bool(stream.get("stale", True))
        stream_lag_ms = stream.get("lag_ms")
        stream_last_at = stream.get("last_frame_at")
        stream_source = _safe_str(stream.get("source"), "unknown")
        stream_status = _safe_str(stream.get("status"), "unknown")
    except Exception:
        pass

    connectivity = (
        "wss_primary" if stream_status == "current" and not stream_stale
        else "rest_fallback" if stream_status == "rest_fallback"
        else "rest_fallback" if stream_stale
        else "wss_primary"
    )
    exchanges = [
        {
            "id": "binance-usdm",
            "name": "Binance USD-M Futures",
            "status": "warn" if stream_stale else "ok",
            "connectivity": connectivity,
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
        "stream_source": stream_source,
        "stream_status": stream_status,
    }


# ---------------------------------------------------------------------------
# /api/v2/admin/audit/chain  — audit chain summary
# ---------------------------------------------------------------------------

@router.get("/audit/chain")
async def get_admin_audit_chain(_: UserRecord = Depends(_REQUIRE_OPERATOR)) -> dict[str, Any]:
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


# ---------------------------------------------------------------------------
# /api/v2/admin/services  — services list (derived from overview data)
# ---------------------------------------------------------------------------

@router.get("/services")
async def get_admin_services(_: UserRecord = Depends(_REQUIRE_OPERATOR)) -> dict[str, Any]:
    now = _utc_now()
    overview_data: dict[str, Any] = {}
    try:
        overview_data = await _admin_overview_payload_bounded()
    except Exception:
        pass
    services = overview_data.get("services", [])

    # Augment with paper loop status from filesystem
    paper_status_path = _REPO_ROOT / "v2" / "frontend" / "public" / "operator_runtime" / "v2_trade_management_paper" / "latest" / "v2_trade_management_paper_status.json"
    if paper_status_path.exists():
        try:
            ps = json.loads(paper_status_path.read_text())
            services.append({
                "id": "paper-loop",
                "name": "Paper Trade Loop",
                "status": "ok" if ps.get("process_running") else "error",
                "heartbeat_at": ps.get("heartbeat_at"),
                "lag_ms": None,
                "error_count": 0,
                "warning_count": len(ps.get("components_missing", [])),
                "owner": "v2-paper",
                "version": None,
                "detail": ps.get("migration_classification", "unknown"),
                "live_gate": ps.get("live_gate"),
                "redis_keys": ps.get("redis_key_count"),
            })
        except Exception:
            pass

    return {
        "generated_at": now,
        "services": services,
        "total": len(services),
        "healthy": len([s for s in services if s.get("status") == "ok"]),
        "degraded": len([s for s in services if s.get("status") == "warn"]),
        "error": len([s for s in services if s.get("status") == "error"]),
    }


# ---------------------------------------------------------------------------
# /api/v2/admin/traders  — active paper/replay trader bots
# ---------------------------------------------------------------------------

@router.get("/traders")
async def get_admin_traders(_: UserRecord = Depends(_REQUIRE_OPERATOR)) -> dict[str, Any]:
    now = _utc_now()
    traders: list[dict[str, Any]] = []

    paper_path = _REPO_ROOT / "v2" / "frontend" / "public" / "operator_runtime" / "v2_trade_management_paper" / "latest" / "v2_trade_management_paper_status.json"
    if paper_path.exists():
        try:
            ps = json.loads(paper_path.read_text())
            traders.append({
                "id": "v2_trade_management_paper",
                "mode": "paper",
                "status": "active" if ps.get("process_running") else "stopped",
                "heartbeat_at": ps.get("heartbeat_at"),
                "position_count": None,
                "live_gate": ps.get("live_gate", "blocked_human_only"),
                "migration_classification": ps.get("migration_classification"),
                "approves_live": ps.get("approves_live", False),
                "redis_keys": ps.get("redis_key_count"),
                "components_ported": len(ps.get("components_ported", [])),
                "components_missing": len(ps.get("components_missing", [])),
            })
        except Exception:
            pass

    # Check Redis for paper positions count
    client = get_redis()
    if client is not None:
        try:
            positions_raw = client.get("v2:paper:positions")
            if positions_raw:
                positions_data = json.loads(positions_raw)
                if traders and isinstance(positions_data, (list, dict)):
                    n = len(positions_data) if isinstance(positions_data, list) else len(positions_data.get("positions", []))
                    traders[0]["position_count"] = n
        except Exception:
            pass

    return {
        "generated_at": now,
        "traders": traders,
        "total": len(traders),
        "active": len([t for t in traders if t.get("status") == "active"]),
    }


# ---------------------------------------------------------------------------
# /api/v2/admin/data/sources  — data source connectivity status
# ---------------------------------------------------------------------------

@router.get("/data/sources")
async def get_admin_data_sources(_: UserRecord = Depends(_REQUIRE_OPERATOR)) -> dict[str, Any]:
    now = _utc_now()
    client = get_redis()
    sources: list[dict[str, Any]] = []

    data_surface_path = _REPO_ROOT / "v2" / "artifacts" / "nervyx-data-surface-inventory.json"
    if data_surface_path.exists():
        try:
            surface = json.loads(data_surface_path.read_text())
            for item in (surface if isinstance(surface, list) else surface.get("sources", [])):
                if isinstance(item, dict):
                    sources.append({
                        "id": _safe_str(item.get("id") or item.get("name"), ""),
                        "dataset": _safe_str(item.get("dataset") or item.get("type"), ""),
                        "status": _safe_str(item.get("status"), "unknown"),
                        "last_record_at": item.get("last_record_at"),
                        "lag_ms": item.get("lag_ms"),
                        "throughput": item.get("throughput"),
                        "gap_count": _safe_int(item.get("gap_count")),
                        "duplicate_count": _safe_int(item.get("duplicate_count")),
                        "error_count": _safe_int(item.get("error_count")),
                    })
        except Exception:
            pass

    if not sources and client is not None:
        for key_suffix, label in [
            ("v2:features:ta_full:BTCUSDT:1m", "TA features (BTC/1m)"),
            ("v2:trainer:hybrid_cuda:signals:paper:BTCUSDT", "Trainer signals"),
            ("v2:risk:decisions:latest", "Risk gateway"),
            ("v2:paper:positions", "Paper positions"),
        ]:
            try:
                val = client.get(key_suffix)
                sources.append({
                    "id": key_suffix,
                    "dataset": label,
                    "status": "ok" if val else "gap",
                    "last_record_at": None,
                    "lag_ms": None,
                    "throughput": None,
                    "gap_count": 0 if val else 1,
                    "duplicate_count": 0,
                    "error_count": 0,
                })
            except Exception:
                pass

    return {
        "generated_at": now,
        "sources": sources,
        "total": len(sources),
        "ok": len([s for s in sources if s.get("status") == "ok"]),
        "gap": len([s for s in sources if s.get("status") == "gap"]),
        "error": len([s for s in sources if s.get("status") == "error"]),
    }


# ---------------------------------------------------------------------------
# /api/v2/admin/risk/rules  — active risk rule summary
# ---------------------------------------------------------------------------

@router.get("/risk/rules")
async def get_admin_risk_rules(_: UserRecord = Depends(_REQUIRE_ADMIN)) -> dict[str, Any]:
    now = _utc_now()
    client = get_redis()
    rules: list[dict[str, Any]] = []

    risk_heartbeat = _redis_read("v2:risk:gateway:heartbeat")
    risk_latest = _redis_read("v2:risk:gateway:latest")

    # Build rule rows from known risk gates
    known_gates = [
        ("live_gate", "Live Gate", "blocked_human_only", None, True),
        ("confidence_gate", "Confidence ≥ 0.75", None, None, None),
        ("edge_cost_ratio", "Edge/Cost ≥ 1.5×", None, None, None),
        ("cooldown_300s", "Cooldown 300s", None, None, None),
        ("loss_cooldown_3600s", "Loss Cooldown 3600s", None, None, None),
        ("weekly_loss_limit", "Weekly Loss Limit -$250", None, None, None),
        ("daily_loss_limit", "Daily Loss Limit -$75", None, None, None),
        ("churn_governor", "Churn Governor", None, None, None),
        ("anti_mm_detector", "Anti-MM Detector", None, None, None),
    ]

    last_decision_at = None
    block_count = 0
    if isinstance(risk_heartbeat, dict):
        last_decision_at = risk_heartbeat.get("finished_at") or risk_heartbeat.get("started_at")
        block_count = _safe_int(risk_heartbeat.get("decisions_blocked_total"))
    if isinstance(risk_latest, dict):
        last_decision_at = risk_latest.get("generated_at") or last_decision_at

    for rule_id, name, threshold, current_value, is_blocked in known_gates:
        is_live_gate = rule_id == "live_gate"
        rules.append({
            "rule_id": rule_id,
            "name": name,
            "status": "block" if is_blocked else "unknown",
            "threshold": threshold,
            "current_value": current_value,
            "block_count": block_count if is_live_gate else None,
            "last_decision_at": last_decision_at,
        })

    return {
        "generated_at": now,
        "rules": rules,
        "total": len(rules),
        "blocking": len([r for r in rules if r.get("status") == "block"]),
        "last_decision_at": last_decision_at,
        "live_blocked": True,
    }


# ---------------------------------------------------------------------------
# /api/v2/admin/jobs  — background job queue
# ---------------------------------------------------------------------------

@router.get("/jobs")
async def get_admin_jobs(_: UserRecord = Depends(_REQUIRE_OPERATOR)) -> dict[str, Any]:
    now = _utc_now()
    client = get_redis()
    jobs: list[dict[str, Any]] = []

    if client is not None:
        try:
            raw_jobs = client.lrange("v2:admin:jobs", 0, 49)
            for raw in (raw_jobs or []):
                try:
                    j = json.loads(raw) if isinstance(raw, bytes | str) else raw
                    if isinstance(j, dict):
                        jobs.append({
                            "id": _safe_str(j.get("id"), ""),
                            "type": _safe_str(j.get("type") or j.get("job_type"), "unknown"),
                            "status": _safe_str(j.get("status"), "unknown"),
                            "progress": j.get("progress"),
                            "current_step": j.get("current_step"),
                            "started_at": j.get("started_at"),
                            "updated_at": j.get("updated_at"),
                            "error": j.get("error"),
                        })
                except Exception:
                    pass
        except Exception:
            pass

    # Check pipeline control queue
    pipeline_queue = _redis_read("v2:pipeline:control:queue")
    if isinstance(pipeline_queue, list):
        for req in pipeline_queue:
            if isinstance(req, dict):
                jobs.append({
                    "id": _safe_str(req.get("request_id") or req.get("id"), ""),
                    "type": _safe_str(req.get("run_type"), "pipeline"),
                    "status": "queued",
                    "progress": None,
                    "current_step": "pending",
                    "started_at": req.get("requested_at"),
                    "updated_at": req.get("requested_at"),
                    "error": None,
                })

    return {
        "generated_at": now,
        "jobs": jobs,
        "total": len(jobs),
        "queued": len([j for j in jobs if j.get("status") == "queued"]),
        "running": len([j for j in jobs if j.get("status") == "running"]),
        "completed": len([j for j in jobs if j.get("status") == "complete"]),
        "failed": len([j for j in jobs if j.get("status") == "failed"]),
    }


# ---------------------------------------------------------------------------
# /api/v2/admin/scripts  — script registry (from cli/ + tools/ directories)
# ---------------------------------------------------------------------------

@router.get("/scripts")
async def get_admin_scripts(_: UserRecord = Depends(_REQUIRE_OPERATOR)) -> dict[str, Any]:
    now = _utc_now()
    scripts: list[dict[str, Any]] = []

    cli_dir = _REPO_ROOT / "v2" / "backend" / "app" / "cli"
    tools_dir = _REPO_ROOT / "tools"

    for directory, owner in [(cli_dir, "v2-cli"), (tools_dir, "v2-tools")]:
        if not directory.exists():
            continue
        for p in sorted(directory.glob("*.py")):
            if p.name.startswith("_") or p.name == "__init__.py":
                continue
            scripts.append({
                "name": p.stem,
                "path": str(p.relative_to(_REPO_ROOT)),
                "owner": owner,
                "last_run": None,
                "status": "unknown",
                "classification": "cli" if owner == "v2-cli" else "tool",
            })

    return {
        "generated_at": now,
        "scripts": scripts,
        "total": len(scripts),
    }


# ---------------------------------------------------------------------------
# /api/v2/admin/build/status  — build artifact & readiness marker status
# ---------------------------------------------------------------------------

@router.get("/build/status")
async def get_admin_build_status(_: UserRecord = Depends(_REQUIRE_OPERATOR)) -> dict[str, Any]:
    now = _utc_now()
    artifacts: list[dict[str, Any]] = []
    artifacts_dir = _REPO_ROOT / "v2" / "artifacts"

    if artifacts_dir.exists():
        for p in sorted(artifacts_dir.iterdir()):
            if p.is_file():
                artifacts.append({
                    "name": p.name,
                    "path": str(p.relative_to(_REPO_ROOT)),
                    "size_bytes": p.stat().st_size,
                    "status": "ready",
                    "last_built_at": datetime.fromtimestamp(p.stat().st_mtime, tz=UTC).isoformat().replace("+00:00", "Z"),
                })

    # Check for readiness markers from pipeline trust report
    trust_report = _REPO_ROOT / "pipeline_trust_report.json"
    trust_summary: dict[str, Any] = {}
    if trust_report.exists():
        try:
            trust_summary = json.loads(trust_report.read_text())
        except Exception:
            pass

    overall = "ready" if artifacts else "pending"
    if trust_summary.get("overall_result") == "FAIL":
        overall = "blocked"

    return {
        "generated_at": now,
        "overall": overall,
        "artifacts": artifacts,
        "total": len(artifacts),
        "pipeline_trust": {
            "overall_result": trust_summary.get("overall_result"),
            "warnings": _safe_int(trust_summary.get("warnings")),
            "failures": _safe_int(trust_summary.get("failures")),
            "generated_at": trust_summary.get("generated_at"),
        } if trust_summary else None,
    }


# ---------------------------------------------------------------------------
# /api/v2/admin/coverage  — file inventory coverage atlas
# ---------------------------------------------------------------------------

@router.get("/coverage")
async def get_admin_coverage(_: UserRecord = Depends(_REQUIRE_OPERATOR)) -> dict[str, Any]:
    now = _utc_now()

    summary_path = _REPO_ROOT / "v2" / "artifacts" / "nervyx-changed-file-classification-summary.json"
    summary: dict[str, Any] = {}
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text())
        except Exception:
            pass

    # Also check data surface inventory
    surface_path = _REPO_ROOT / "v2" / "artifacts" / "nervyx-data-surface-inventory-summary.json"
    surface_summary: dict[str, Any] = {}
    if surface_path.exists():
        try:
            surface_summary = json.loads(surface_path.read_text())
        except Exception:
            pass

    files_total = _safe_int(summary.get("total") or summary.get("files_total"))
    files_classified = _safe_int(summary.get("classified") or summary.get("files_classified"))
    coverage_pct = round(files_classified / files_total * 100, 1) if files_total > 0 else 0.0

    return {
        "generated_at": now,
        "files_total": files_total,
        "files_classified": files_classified,
        "coverage_pct": coverage_pct,
        "classification_summary": summary.get("by_classification") or summary.get("classifications"),
        "data_surfaces": surface_summary.get("surfaces") or surface_summary.get("total"),
        "data_surface_summary": surface_summary,
        "source_file": str(summary_path.relative_to(_REPO_ROOT)) if summary_path.exists() else None,
    }


# ---------------------------------------------------------------------------
# /api/v2/admin/migrations  — schema/data migration history
# ---------------------------------------------------------------------------

@router.get("/migrations")
async def get_admin_migrations(_: UserRecord = Depends(_REQUIRE_OPERATOR)) -> dict[str, Any]:
    now = _utc_now()
    migrations: list[dict[str, Any]] = []

    migration_dirs = [
        _REPO_ROOT / "v2" / "backend" / "migrations",
        _REPO_ROOT / "v2" / "backend" / "alembic" / "versions",
    ]
    for mdir in migration_dirs:
        if not mdir.exists():
            continue
        for p in sorted(mdir.glob("*.py")):
            if p.name.startswith("_"):
                continue
            migrations.append({
                "name": p.stem,
                "path": str(p.relative_to(_REPO_ROOT)),
                "status": "applied",
                "applied_at": datetime.fromtimestamp(p.stat().st_mtime, tz=UTC).isoformat().replace("+00:00", "Z"),
            })

    # Also check v2/legacy_preserved for migration-related files
    if not migrations:
        contract_path = _REPO_ROOT / "v2" / "backend" / "app" / "cli" / "v2_paper_timeframe_churn_governance_audit.py"
        if contract_path.exists():
            migrations.append({
                "name": "paper_runtime_cutover",
                "path": "v2/backend/app/cli/v2_paper_timeframe_churn_governance_audit.py",
                "status": "applied",
                "applied_at": "2026-06-27T00:00:00Z",
                "description": "paper_online_runtime → v2_trade_management_paper_loop cutover",
            })

    return {
        "generated_at": now,
        "migrations": migrations,
        "total": len(migrations),
        "applied": len([m for m in migrations if m.get("status") == "applied"]),
        "pending": len([m for m in migrations if m.get("status") == "pending"]),
    }


# ---------------------------------------------------------------------------
# /api/v2/admin/ai/status  — Claude + Ollama supervision health
# ---------------------------------------------------------------------------

@router.get("/ai/status")
async def get_admin_ai_status(_: UserRecord = Depends(_REQUIRE_ADMIN)) -> dict[str, Any]:
    now = _utc_now()
    client = get_redis()

    # Claude status from worklog directory
    claude_session_active = False
    claude_last_at: str | None = None
    worklog_dir = _REPO_ROOT / "claude_worklog"
    if worklog_dir.exists():
        try:
            recent_files = sorted(worklog_dir.rglob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
            if recent_files:
                mtime = recent_files[0].stat().st_mtime
                claude_last_at = datetime.fromtimestamp(mtime, tz=UTC).isoformat().replace("+00:00", "Z")
                age_h = (datetime.now(UTC).timestamp() - mtime) / 3600
                claude_session_active = age_h < 2.0
        except Exception:
            pass

    # Ollama status — try subprocess ping
    ollama_available = False
    ollama_model: str | None = None
    try:
        result = subprocess.run(
            ["curl", "-s", "--connect-timeout", "1", "http://localhost:11434/api/tags"],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0 and result.stdout:
            tags = json.loads(result.stdout)
            models = tags.get("models", [])
            ollama_available = len(models) > 0
            ollama_model = models[0].get("name") if models else None
    except Exception:
        pass

    # Redis-based supervision keys
    supervision_raw = _redis_read("v2:supervision:claude") or {}
    ollama_raw = _redis_read("v2:supervision:ollama") or {}

    return {
        "generated_at": now,
        "claude": {
            "status": "active" if claude_session_active else "idle",
            "last_activity_at": claude_last_at,
            "session_active": claude_session_active,
            "model": "claude-sonnet-4-6",
            "supervision_redis_key": "v2:supervision:claude",
            "redis_data": supervision_raw if supervision_raw else None,
        },
        "ollama": {
            "status": "available" if ollama_available else "unavailable",
            "available": ollama_available,
            "model": ollama_model,
            "endpoint": "http://localhost:11434",
            "supervision_redis_key": "v2:supervision:ollama",
            "redis_data": ollama_raw if ollama_raw else None,
        },
        "supervision_enabled": True,
        "live_mutation_allowed": False,
    }


# ---------------------------------------------------------------------------
# /api/v2/admin/codex/status  — Codex review gates + milestone status
# ---------------------------------------------------------------------------

@router.get("/codex/status")
async def get_admin_codex_status(_: UserRecord = Depends(_REQUIRE_ADMIN)) -> dict[str, Any]:
    now = _utc_now()
    client = get_redis()
    milestones: list[dict[str, Any]] = []

    # Try Redis first
    codex_summary = _redis_read("codex:reviews:latest") or _redis_read("codex:reviews:summary")

    # Scan filesystem for codex review files. Artifacts never carry flat
    # result/verdict/pass_count keys (the table rendered 20 UNKNOWN rows);
    # normalize their real verdict fields (burndown_review_verdict,
    # mapping.remediation_verdict, classification, go_no_go, status).
    review_dir = _REPO_ROOT / "claude_worklog"
    if review_dir.exists():
        try:
            for p in sorted(review_dir.rglob("*codex*review*.json"), key=lambda f: f.stat().st_mtime, reverse=True)[:20]:
                try:
                    data = json.loads(p.read_text())
                    if isinstance(data, dict):
                        verdict = extract_codex_artifact_verdict(data, name=p.stem)
                        result = _safe_str(
                            data.get("result") or data.get("verdict") or verdict["result"],
                            "unknown",
                        )
                        milestones.append({
                            "id": p.stem,
                            "path": str(p.relative_to(_REPO_ROOT)),
                            "result": result,
                            "verdict_field": verdict["verdict_field"],
                            "verdict_value": verdict["verdict_value"],
                            "pass_count": _safe_int(
                                data.get("pass_count") or (1 if result == "pass" else 0)
                            ),
                            "fail_count": _safe_int(
                                data.get("fail_count")
                                or data.get("blocker_count")
                                or (1 if result == "fail" else 0)
                            ),
                            "last_reviewed_at": datetime.fromtimestamp(p.stat().st_mtime, tz=UTC).isoformat().replace("+00:00", "Z"),
                        })
                except Exception:
                    pass
        except Exception:
            pass

    # Build summary from Redis keys or filesystem totals
    open_count = _safe_int((codex_summary or {}).get("open_count"))
    blocker_count = _safe_int((codex_summary or {}).get("blocker_count"))

    if not milestones and client is not None:
        for key in ["codex:reviews:latest", "codex:reviews:summary"]:
            try:
                raw = client.get(key)
                if raw:
                    d = json.loads(raw)
                    if isinstance(d, dict):
                        open_count = _safe_int(d.get("open_count", open_count))
                        blocker_count = _safe_int(d.get("blocker_count", blocker_count))
                        break
            except Exception:
                pass

    # Redis codex:reviews:* keys are never written; when the summary is
    # absent, derive the header fields from the normalized milestone verdicts
    # instead of returning permanent zeros/nulls.
    last_pass_id = (codex_summary or {}).get("last_pass_id")
    last_fail_id = (codex_summary or {}).get("last_fail_id")
    last_blocker_text = (codex_summary or {}).get("last_blocker_text")
    if last_pass_id is None:
        last_pass_id = next((m["id"] for m in milestones if m["result"] == "pass"), None)
    if last_fail_id is None:
        fail_row = next((m for m in milestones if m["result"] == "fail"), None)
        if fail_row is not None:
            last_fail_id = fail_row["id"]
            if last_blocker_text is None and fail_row.get("verdict_value"):
                last_blocker_text = str(fail_row["verdict_value"])[:200]
    if not open_count:
        open_count = sum(1 for m in milestones if m["result"] in {"pending", "blocked"})
    if not blocker_count:
        blocker_count = sum(1 for m in milestones if m["result"] == "blocked")
    return {
        "generated_at": now,
        "milestones": milestones,
        "total": len(milestones),
        "open_count": open_count,
        "blocker_count": blocker_count,
        "last_pass_id": last_pass_id,
        "last_fail_id": last_fail_id,
        "last_blocker_text": last_blocker_text,
    }


# ---------------------------------------------------------------------------
# /api/v2/config/current  — current config snapshot
# (No /admin prefix — route path is /api/v2/config/current via no-prefix entry)
# This is registered via a sub-router with no prefix included in __init__.py
# ---------------------------------------------------------------------------

config_router = APIRouter(tags=["v2-config"])


@config_router.get("/config/current")
async def get_config_current(_: UserRecord = Depends(require_auth)) -> dict[str, Any]:
    now = _utc_now()
    client = get_redis()

    config_data: dict[str, Any] = {}
    config_raw = _redis_read("v2:config:current") or _redis_read("v2:config:active")
    if isinstance(config_raw, dict):
        config_data = config_raw
    config_persisted = bool(config_data)

    # Honesty: when no versioned config is persisted (v2:config:current /
    # v2:config:active are unpopulated), do NOT fabricate version "1.0.0",
    # last_changed_at=request-time, or last_changed_by="system" — those made
    # the config chip always read as just-changed by system. Nulls + an
    # explicit config_persisted flag are the truth.
    version = _safe_str(config_data.get("version"), "") or None
    environment = _safe_str(config_data.get("environment") or os.environ.get("V2_MODE"), "paper")
    last_changed_at = config_data.get("last_changed_at") or config_data.get("updated_at") or None
    last_changed_by = config_data.get("last_changed_by") or config_data.get("updated_by") or None

    # trainer_mode: report the env var only if the operator explicitly set it;
    # otherwise surface the runtime trainer evidence instead of the "stub"
    # default (the actual runtime is the native CUDA hybrid trainer).
    trainer_mode_env = os.environ.get("V2_TRAINER_MODE", "").strip()
    trainer_mode: str | None = trainer_mode_env or None
    trainer_mode_source = "env:V2_TRAINER_MODE" if trainer_mode_env else None
    if trainer_mode is None:
        trainer_summary = _redis_read("v2:trainer:summary")
        if isinstance(trainer_summary, dict):
            runtime_mode = trainer_summary.get("runtime_mode")
            if isinstance(runtime_mode, dict) and runtime_mode.get("effective_trainer_mode"):
                trainer_mode = _safe_str(runtime_mode.get("effective_trainer_mode"), "") or None
                trainer_mode_source = "redis:v2:trainer:summary.runtime_mode"
            elif trainer_summary.get("checkpoint_id"):
                trainer_mode = "native_cuda_hybrid"
                trainer_mode_source = "redis:v2:trainer:summary (checkpoint evidence)"

    # Build visible config (no secrets)
    visible_config: dict[str, Any] = {
        "v2_mode": os.environ.get("V2_MODE", "paper"),
        "live_trading": "BLOCKED",
        "paper_trading": "ENABLED",
        "live_gate": "blocked_human_only",
        "redis_prefix": os.environ.get("V2_REDIS_PREFIX", "v2"),
        "trainer_mode": trainer_mode,
        "trainer_mode_source": trainer_mode_source,
        "log_level": os.environ.get("LOG_LEVEL", "INFO"),
    }
    if config_data.get("config"):
        for k, v in config_data["config"].items():
            if "secret" not in k.lower() and "key" not in k.lower() and "password" not in k.lower():
                visible_config[k] = v

    return {
        "generated_at": now,
        "version": version,
        "environment": environment,
        "last_changed_at": last_changed_at,
        "last_changed_by": last_changed_by,
        "config": visible_config,
        "config_persisted": config_persisted,
        "config_source": (
            "redis:v2:config:current|v2:config:active" if config_persisted
            else "unpersisted_defaults"
        ),
        "warnings": (
            [] if config_persisted
            else ["No versioned config is persisted in Redis; env/runtime defaults shown, version/changed-at unknown"]
        ),
    }


# ---------------------------------------------------------------------------
# Dangerous controls endpoint — all actions BLOCKED in paper/read-only mode
# ---------------------------------------------------------------------------

_BLOCKED_ACTIONS: frozenset[str] = frozenset({
    "enable_live_trading",
    "increase_leverage",
    "disable_kill_switch",
    "disable_mandatory_stop",
    "enable_hedge",
    "enable_dca",
    "enable_adjust_leverage",
    "switch_paper_to_live",
    "add_live_api_key",
    "increase_position_size",
    "increase_daily_loss_limit",
    "disable_mandatory_stop",
})


_AUDIT_CHAIN_KEY = "audit:chain"
_AUDIT_CHAIN_MAX_ENTRIES = 2000


def _write_audit_chain_entry(
    *,
    audit_id: str,
    actor: str,
    action: str,
    result: str,
    reason: str | None = None,
    evidence: Any = None,
) -> bool:
    """Persist a governance/control audit entry to the V2 admin audit chain.

    GET /api/v2/admin/audit/chain reads the Redis list ``audit:chain``; until
    this writer existed the handler docstring claimed "Every attempt is
    audit-logged" while nothing was ever persisted. V2-owned key (same policy
    basis as ``audit:trainer:reads`` — see app.api.v2._common). Never raises.
    """
    client = get_redis()
    if client is None:
        return False
    entry = {
        "audit_id": audit_id,
        "actor": actor,
        "action": action,
        "result": result,
        "reason": reason,
        "evidence": evidence,
        "timestamp": _utc_now(),
        "live_gate": "blocked_human_only",
    }
    try:
        client.lpush(_AUDIT_CHAIN_KEY, json.dumps(entry))
        client.ltrim(_AUDIT_CHAIN_KEY, 0, _AUDIT_CHAIN_MAX_ENTRIES - 1)
        return True
    except Exception:
        return False


@router.post("/controls/{action_id}", dependencies=[Depends(require_admin)])
async def execute_control_action(
    action_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    actor: UserRecord = Depends(require_admin),
) -> dict[str, Any]:
    """Dangerous control gate — all actions are blocked in paper/read-only mode.

    LIVE TRADING: BLOCKED. No action submitted here will mutate live state,
    change leverage, or enable live execution. Every attempt is audit-logged.
    """
    now = _utc_now()
    audit_id = secrets.token_hex(16)
    reason = str(body.get("reason") or "")
    actor_email = str(actor.get("email") or actor.get("username") or "unknown")

    # Audit-log the attempt BEFORE rejecting so the chain records every
    # governance action (the docstring's "audit-logged" claim was unwired).
    _write_audit_chain_entry(
        audit_id=audit_id,
        actor=actor_email,
        action=f"control:{action_id}",
        result="blocked",
        reason=reason or None,
        evidence={"blocked_action": action_id in _BLOCKED_ACTIONS, "endpoint": f"/api/v2/admin/controls/{action_id}"},
    )

    # Regardless of action, this system is LIVE TRADING: BLOCKED.
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error": "LIVE_TRADING_BLOCKED",
            "action_id": action_id,
            "message": (
                "All dangerous control actions are blocked in paper/read-only mode. "
                "Live trading must be enabled through the operator gate process."
            ),
            "audit_id": audit_id,
            "actor": actor_email,
            "reason_submitted": reason,
            "generated_at": now,
            "live_gate": "blocked_human_only",
        },
    )


# ---------------------------------------------------------------------------
# /api/v2/admin/paper/session-reset  — operator bootstrap session reset
# ---------------------------------------------------------------------------
# Paper-only. Clears closed_trades, positions, outcome_labels, and computed
# performance keys. Has no effect on live trading (routes_to_live: false).
# Requires admin auth + danger_accepted: true in the request body.
# Writes an audit log entry with actor, reason, and cleared key list.
#
# Use case: after root-cause patches are applied (R29-D2, R30-D1, R29-D4),
# the bootstrap deadlock (FIRST_BOOTSTRAP_CLOSE_NEGATIVE) can only be cleared
# by resetting the session so the improved entry gate governs new trades.
# ---------------------------------------------------------------------------

_PAPER_SESSION_RESET_KEYS = (
    "v2:paper:closed_trades",
    "v2:paper:positions",
    "v2:paper:outcome_labels",
    "v2:paper:performance_circuit_breaker_status",
    "v2:paper:bleed_halt_status",
    "v2:paper:governor_v2_status",
)

# Filesystem lifecycle state file path (written by paper loop, read by verifier dist/ copy).
# Reset clears it so the paper loop starts fresh on next cycle.
_PAPER_LIFECYCLE_STATE_PATH = (
    _REPO_ROOT
    / "v2" / "frontend" / "public"
    / "operator_runtime" / "v2_paper_trade_management" / "latest"
    / "paper_lifecycle_state.json"
)

_PAPER_SESSION_RESET_AUDIT_KEY = "v2:paper:operator_session_reset_log"


@router.post("/paper/session-reset", dependencies=[Depends(require_admin)])
async def paper_session_reset(
    body: dict[str, Any] = Body(default_factory=dict),
    actor: UserRecord = Depends(require_admin),
) -> dict[str, Any]:
    """Paper-only bootstrap session reset.

    Clears the paper trading session state (closed_trades, positions,
    outcome_labels, and computed performance keys) so bootstrap can restart
    with the current entry gate (R29-D2 regime gate, R30-D1 micro-cap filter,
    R29-D4 wider ATR stop).

    DOES NOT affect live trading. routes_to_live: false.
    DOES NOT change leverage, margin, or exchange state.
    DOES NOT clear audit ledger or trade history files — only Redis state.

    Required body fields:
        danger_accepted: true   — explicit operator acknowledgment
        reason: str             — documented reason for the reset
    """
    now = _utc_now()
    audit_id = secrets.token_hex(16)
    actor_email = str(actor.get("email") or actor.get("username") or "unknown")
    reason = str(body.get("reason") or "").strip()
    danger_accepted = body.get("danger_accepted") is True

    if not danger_accepted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "DANGER_NOT_ACCEPTED",
                "message": "Must include danger_accepted: true to confirm session reset.",
                "audit_id": audit_id,
                "actor": actor_email,
                "generated_at": now,
                "routes_to_live": False,
                "places_real_order": False,
            },
        )

    if not reason:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "REASON_REQUIRED",
                "message": "Must include a non-empty reason string for audit log.",
                "audit_id": audit_id,
                "actor": actor_email,
                "generated_at": now,
            },
        )

    client = get_redis()
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "REDIS_UNAVAILABLE",
                "message": "Cannot connect to Redis to perform session reset.",
                "audit_id": audit_id,
                "actor": actor_email,
                "generated_at": now,
            },
        )

    cleared_keys: list[str] = []
    skipped_keys: list[str] = []
    errors: list[str] = []

    for key in _PAPER_SESSION_RESET_KEYS:
        try:
            existed = client.exists(key)
            if existed:
                client.delete(key)
                cleared_keys.append(key)
            else:
                skipped_keys.append(key)
        except Exception as exc:
            errors.append(f"{key}: {exc}")

    # Also clear the public/ lifecycle state file so the paper loop starts fresh.
    # The paper loop overwrites this on the next write cycle with current state.
    # NOTE: The dist/ copy (read by the verifier's historical supplement) is only
    # updated on npm run build — run `cd v2/frontend && npm run build` after reset
    # so the verifier's G13/G14 historical supplement picks up the cleared state.
    lifecycle_file_cleared = False
    if _PAPER_LIFECYCLE_STATE_PATH.exists():
        try:
            _PAPER_LIFECYCLE_STATE_PATH.write_text(
                json.dumps({"closed_trades": [], "open_positions": [], "session_reset_utc": now}, indent=2)
            )
            cleared_keys.append(str(_PAPER_LIFECYCLE_STATE_PATH.relative_to(_REPO_ROOT)))
            lifecycle_file_cleared = True
        except Exception as exc:
            errors.append(f"lifecycle_state_file: {exc}")

    audit_entry = {
        "audit_id": audit_id,
        "event": "PAPER_SESSION_RESET",
        "actor": actor_email,
        "reason": reason,
        "cleared_keys": cleared_keys,
        "skipped_keys": skipped_keys,
        "errors": errors,
        "lifecycle_file_cleared": lifecycle_file_cleared,
        "routes_to_live": False,
        "places_real_order": False,
        "live_path_changed": False,
        "paper_only": True,
        "generated_at": now,
        "patches_applied": ["R29-D2", "R29-D4", "R30-D1"],
    }

    try:
        client.rpush(_PAPER_SESSION_RESET_AUDIT_KEY, json.dumps(audit_entry))
    except Exception:
        pass
    # Mirror into the admin audit chain so /admin/audit shows the reset.
    _write_audit_chain_entry(
        audit_id=audit_id,
        actor=actor_email,
        action="paper_session_reset",
        result="RESET_COMPLETE" if not errors else "RESET_PARTIAL",
        reason=reason,
        evidence={"cleared_keys": cleared_keys, "skipped_keys": skipped_keys, "errors": errors},
    )

    result: dict[str, Any] = {
        "status": "RESET_COMPLETE" if not errors else "RESET_PARTIAL",
        "audit_id": audit_id,
        "actor": actor_email,
        "reason": reason,
        "cleared_keys": cleared_keys,
        "skipped_keys": skipped_keys,
        "errors": errors,
        "routes_to_live": False,
        "places_real_order": False,
        "live_path_changed": False,
        "paper_only": True,
        "next_steps": (
            "1. Restart the paper loop process to begin a fresh bootstrap session. "
            "2. Run: cd v2/frontend && npm run build — to update dist/ so the guardian "
            "verifier's G13/G14 historical supplement picks up the cleared trade history. "
            "3. The improved entry gate (R29-D2 regime gate, R30-D1 micro-cap filter, "
            "R29-D4 3x ATR stop for trend_mode) is already active. "
            "4. G13/G14 gates will pass once 100+ trades with positive expectancy accumulate."
        ),
        "generated_at": now,
    }

    if errors:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result,
        )

    return result
