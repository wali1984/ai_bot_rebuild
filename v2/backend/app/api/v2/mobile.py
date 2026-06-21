"""Mobile-optimized compact API endpoints for iOS/iPadOS/watchOS app.

All endpoints are read-only. Live trading actions require human approval
through the web admin interface — no live trade execution from mobile.

Auth: Bearer token via Authorization header (same JWT as web session).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.api.v2._common import get_redis
from app.auth.security import optional_auth, require_auth
from app.auth.users import UserRecord

router = APIRouter(prefix="/mobile", tags=["v2-mobile"])


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


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


def _paper_heartbeat(r: Any) -> dict[str, Any]:
    return _redis_get_json(r, "v2:paper:heartbeat") or {}


def _trainer_status_from_redis(r: Any) -> dict[str, Any]:
    return _redis_get_json(r, "v2:trainer:status") or {}


def _gpu_status_from_redis(r: Any) -> dict[str, Any]:
    return _redis_get_json(r, "v2:gpu:status") or {}


def _signal_matrix_from_redis(r: Any, limit: int = 20) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        raw = r.get("v2:signals:matrix")
        if raw:
            matrix = json.loads(raw)
            rows = list(matrix) if isinstance(matrix, list) else []
    except Exception:
        pass
    return rows[:limit]


def _paper_positions_from_redis(r: Any) -> list[dict[str, Any]]:
    try:
        raw = r.get("v2:paper:positions")
        if raw:
            data = json.loads(raw)
            return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def _alerts_from_redis(r: Any, limit: int = 30) -> list[dict[str, Any]]:
    return _redis_lrange_json(r, "v2:market:alerts", 0, limit - 1)


def _risk_status_from_redis(r: Any) -> dict[str, Any]:
    return _redis_get_json(r, "v2:risk:status") or {}


def _live_gate_status() -> dict[str, Any]:
    return {
        "live_trading_enabled": False,
        "places_real_order": False,
        "gate": "blocked_human_only",
        "label": "LIVE TRADING BLOCKED",
    }


# ── Compact model helpers ─────────────────────────────────────────────────────

def _compact_position(pos: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(pos.get("position_id") or pos.get("id") or ""),
        "symbol": str(pos.get("symbol") or ""),
        "side": str(pos.get("side") or ""),
        "qty": _safe_float(pos.get("qty") or pos.get("quantity")),
        "entry_price": _safe_float(pos.get("entry_price")),
        "mark_price": _safe_float(pos.get("mark_price")),
        "unrealized_pnl": _safe_float(pos.get("unrealized_pnl")),
        "realized_pnl": _safe_float(pos.get("realized_pnl")),
        "opened_at": str(pos.get("opened_at") or pos.get("created_at") or ""),
        "status": str(pos.get("status") or "open"),
    }


def _compact_signal(sig: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(sig.get("signal_id") or sig.get("id") or ""),
        "symbol": str(sig.get("symbol") or ""),
        "timeframe": str(sig.get("timeframe") or ""),
        "action": str(sig.get("action") or ""),
        "confidence": _safe_float(sig.get("confidence")),
        "actionable": bool(sig.get("actionable")),
        "risk_state": str(sig.get("risk_state") or ""),
        "paper_fill_status": str(sig.get("paper_fill_status") or ""),
        "published_at": str(sig.get("published_at") or ""),
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
    """Compact system overview for mobile home screen.
    Returns trainer state, GPU, paper loop, open positions summary, top alerts.
    No auth required (public state only).
    """
    try:
        r = get_redis()
    except Exception:
        r = None

    hb = _paper_heartbeat(r) if r else {}
    trainer = _trainer_status_from_redis(r) if r else {}
    gpu = _gpu_status_from_redis(r) if r else {}
    live_gate = _live_gate_status()

    open_count = _safe_int(hb.get("open_position_count") or hb.get("accepted_position_count"))
    closed_count = _safe_int(hb.get("closed_trade_count"))
    realized_pnl = _safe_float(hb.get("realized_pnl_usd"))
    unrealized_pnl = _safe_float(hb.get("unrealized_pnl_usd"))

    alerts_preview: list[dict[str, Any]] = []
    if r:
        raw_alerts = _alerts_from_redis(r, limit=5)
        alerts_preview = [_compact_alert(a) for a in raw_alerts]

    return {
        "generated_utc": _utc_now(),
        "live_gate": live_gate,
        "paper": {
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
            "state": str(trainer.get("state") or "UNKNOWN"),
            "checkpoint": str(trainer.get("checkpoint") or ""),
            "model_source": str(trainer.get("model_source") or ""),
            "cuda_active": bool(trainer.get("cuda_active")),
            "data_coverage": _safe_float(trainer.get("data_coverage")),
            "training_steps_total": _safe_int(trainer.get("training_steps_total")),
            "training_steps_last_hour": _safe_int(trainer.get("training_steps_last_hour")),
        },
        "gpu": {
            "name": str(gpu.get("name") or ""),
            "utilization_pct": _safe_float(gpu.get("utilization_pct")),
            "vram_used_mb": _safe_int(gpu.get("vram_used_mb")),
            "vram_total_mb": _safe_int(gpu.get("vram_total_mb")),
        },
        "alerts_preview": alerts_preview,
        "redis_connected": r is not None,
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
    hb = _paper_heartbeat(r) if r else {}

    positions = [_compact_position(p) for p in raw_positions]
    realized_pnl = _safe_float(hb.get("realized_pnl_usd"))
    unrealized_pnl = _safe_float(hb.get("unrealized_pnl_usd"))
    total_pnl = realized_pnl + unrealized_pnl

    return {
        "generated_utc": _utc_now(),
        "positions": positions,
        "summary": {
            "open_count": len(positions),
            "total_pnl_usd": total_pnl,
            "realized_pnl_usd": realized_pnl,
            "unrealized_pnl_usd": unrealized_pnl,
        },
        "mode": "paper",
        "live_gate": "blocked_human_only",
        "places_real_order": False,
    }


@router.get("/signals")
async def get_mobile_signals(
    limit: int = 20,
    actionable_only: bool = False,
    actor: UserRecord | None = Depends(optional_auth),
) -> dict[str, Any]:
    """Compact signals feed for mobile signals tab. Max 50 rows."""
    limit = min(max(1, limit), 50)
    try:
        r = get_redis()
    except Exception:
        r = None

    raw = _signal_matrix_from_redis(r, limit=limit * 2) if r else []

    if actionable_only:
        raw = [s for s in raw if s.get("actionable")]

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

    trainer_state = str(trainer.get("state") or "UNKNOWN")
    cuda_active = bool(trainer.get("cuda_active"))
    training_active = bool(trainer.get("training_active") or trainer_state.startswith("ACTIVE"))
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
        },
        "gpu": {
            "name": str(gpu.get("name") or ""),
            "utilization_pct": _safe_float(gpu.get("utilization_pct")),
            "vram_used_mb": _safe_int(gpu.get("vram_used_mb")),
            "vram_total_mb": _safe_int(gpu.get("vram_total_mb")),
            "temperature_c": _safe_float(gpu.get("temperature_c")),
        },
        "paper": {
            "classification": paper_classification,
            "open_positions": _safe_int(hb.get("open_position_count")),
            "intents_accepted": _safe_int(hb.get("intents_accepted")),
            "intents_blocked": _safe_int(hb.get("intents_blocked")),
        },
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

    return {
        "generated_utc": _utc_now(),
        "live_gate": _live_gate_status(),
        "risk_state": str(risk.get("state") or "UNKNOWN"),
        "paper_blocked_count": _safe_int(hb.get("intents_blocked")),
        "paper_accepted_count": _safe_int(hb.get("intents_accepted")),
        "kill_switch_active": bool(risk.get("kill_switch_active")),
        "max_position_size_usd": _safe_float(risk.get("max_position_size_usd")),
        "daily_loss_limit_usd": _safe_float(risk.get("daily_loss_limit_usd")),
        "current_daily_loss_usd": _safe_float(risk.get("current_daily_loss_usd")),
        "dangerous_actions_require_human_approval": True,
        "mobile_can_approve_dangerous_actions": False,
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

    signals_seen = _safe_int(hb.get("paper_signals_seen"))
    intents_built = _safe_int(hb.get("intents_built"))
    intents_accepted = _safe_int(hb.get("intents_accepted"))
    intents_blocked = _safe_int(hb.get("intents_blocked"))
    open_count = _safe_int(hb.get("open_position_count") or hb.get("accepted_position_count"))
    closed_count = _safe_int(hb.get("closed_trade_count"))
    realized_pnl = _safe_float(hb.get("realized_pnl_usd"))
    unrealized_pnl = _safe_float(hb.get("unrealized_pnl_usd"))
    outcome_labels = _safe_int(hb.get("outcome_label_count"))
    feedback_consumable = _safe_int(hb.get("trainer_feedback_consumable_row_count"))
    feedback_quarantined = _safe_int(hb.get("trainer_feedback_quarantined_row_count"))

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
        "loop": {
            "signals_seen": signals_seen,
            "intents_built": intents_built,
            "intents_accepted": intents_accepted,
            "intents_blocked": intents_blocked,
            "classification": str(hb.get("classification") or "UNKNOWN"),
        },
        "positions": {
            "open_count": open_count,
            "closed_count": closed_count,
            "positions_preview": [_compact_position(p) for p in positions[:5]],
        },
        "pnl": {
            "realized_usd": realized_pnl,
            "unrealized_usd": unrealized_pnl,
            "total_usd": realized_pnl + unrealized_pnl,
            "win_rate_pct": win_rate,
        },
        "trainer_feedback": {
            "outcome_labels": outcome_labels,
            "consumable_rows": feedback_consumable,
            "quarantined_rows": feedback_quarantined,
        },
    }


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
    """Register an APNS/FCM device token for push notifications.
    Requires authentication.
    """
    if not request.device_token or len(request.device_token) < 8:
        raise HTTPException(status_code=400, detail="invalid_device_token")
    if request.platform not in {"apns", "fcm"}:
        raise HTTPException(status_code=400, detail="unsupported_platform")

    try:
        r = get_redis()
        entry = json.dumps({
            "user_id": str(actor.user_id),
            "device_token": request.device_token,
            "platform": request.platform,
            "environment": request.environment,
            "app_version": request.app_version,
            "registered_at": _utc_now(),
        })
        r.hset(_PUSH_STORE_KEY, request.device_token, entry)
    except Exception:
        pass  # non-fatal; push is best-effort

    return {
        "status": "registered",
        "device_token": request.device_token[:8] + "...",
        "platform": request.platform,
        "registered_at": _utc_now(),
        "note": "Push notifications are best-effort. Delivery depends on APNS/FCM connectivity.",
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
    from app.auth.security import require_admin
    from fastapi import Request as FastAPIRequest
    import inspect

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
            "state": str(trainer.get("state") or "UNKNOWN"),
            "checkpoint": str(trainer.get("checkpoint") or ""),
            "cuda_active": bool(trainer.get("cuda_active")),
            "training_steps_total": _safe_int(trainer.get("training_steps_total")),
            "training_steps_last_hour": _safe_int(trainer.get("training_steps_last_hour")),
        },
        "gpu": {
            "name": str(gpu.get("name") or ""),
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
            "kill_switch_active": bool(risk.get("kill_switch_active")),
        },
        "dangerous_controls_require_web_approval": True,
        "mobile_live_trading_blocked": True,
    }
