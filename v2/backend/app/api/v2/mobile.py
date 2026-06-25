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


def _paper_heartbeat(r: Any) -> dict[str, Any]:
    return _redis_get_json(r, "v2:paper:heartbeat") or {}


def _trainer_status_from_redis(r: Any) -> dict[str, Any]:
    """Read trainer status from v2:trainer:hybrid_cuda:metrics (real data)."""
    metrics = _redis_get_json(r, "v2:trainer:hybrid_cuda:metrics") or {}
    heartbeat = _redis_get_json(r, "v2:trainer:hybrid_cuda:heartbeat") or {}
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


def _signal_matrix_from_redis(r: Any, limit: int = 150) -> list[dict[str, Any]]:
    """Scan v2:signals:latest:* (per-symbol keys) and return sorted list."""
    rows: list[dict[str, Any]] = []
    try:
        # Use pipeline to batch all per-symbol reads
        cursor = 0
        keys: list[str] = []
        while True:
            cursor, batch = r.scan(cursor, match="v2:signals:latest:*", count=200)
            keys.extend(batch)
            if cursor == 0:
                break
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
    return {
        "state": gw.get("current_gate_state") or gw.get("classification") or "UNKNOWN",
        "classification": gw.get("classification") or "",
        "kill_switch_active": bool(gw.get("live_blocked", True)),
        "fail_closed": bool(gw.get("fail_closed", True)),
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

def _compact_position(pos: dict[str, Any]) -> dict[str, Any]:
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
        "decision_reasoning": pos.get("decision_reasoning") if isinstance(pos.get("decision_reasoning"), dict) else None,
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
        "actionable": bool(sig.get("paper_fill_allowed")),
        "risk_state": str(sig.get("risk_state") or ""),
        "paper_fill_status": str(sig.get("paper_fill_status") or ""),
        "published_at": str(sig.get("available_at") or sig.get("decision_time") or ""),
        "last_price": _safe_float(sig.get("last_price")),
        "expected_move_bps": _safe_float(sig.get("expected_move_bps")),
        "data_coverage": _safe_float(sig.get("data_coverage_percent")),
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

    open_count = _safe_int(hb.get("open_position_count") or hb.get("accepted_position_count"))
    closed_count = _safe_int(hb.get("closed_trade_count"))
    realized_pnl = _safe_float(hb.get("realized_pnl_usd"))
    unrealized_pnl = _safe_float(hb.get("unrealized_pnl_usd"))

    alerts_preview: list[dict[str, Any]] = []
    if r:
        raw_alerts = _alerts_from_redis(r, limit=5)
        alerts_preview = [_compact_alert(a) for a in raw_alerts]

    # Signal count from live keys
    signal_count = 0
    if r:
        try:
            cursor, keys = r.scan(0, match="v2:signals:latest:*", count=1)
            signal_count = _safe_int(r.object("encoding", keys[0]) if keys else 0)
            # Actually scan all
            all_sig_keys: list[str] = keys
            while cursor != 0:
                cursor, batch = r.scan(cursor, match="v2:signals:latest:*", count=200)
                all_sig_keys.extend(batch)
            signal_count = len(all_sig_keys)
        except Exception:
            signal_count = 0

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
            "state": trainer.get("state", "UNKNOWN"),
            "checkpoint": trainer.get("checkpoint", ""),
            "model_source": trainer.get("model_source", ""),
            "cuda_active": bool(trainer.get("cuda_active")),
            "device": str(trainer.get("device") or ""),
            "gpu_name": str(trainer.get("gpu_name") or ""),
            "data_coverage": _safe_float(trainer.get("data_coverage")),
            "training_steps_total": _safe_int(trainer.get("training_steps_total")),
            "training_steps_last_hour": _safe_int(trainer.get("training_steps_last_hour")),
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
    realized_pnl = _safe_float(hb.get("realized_pnl_usd"))
    unrealized_pnl = (
        _safe_float(position_pricing.get("unrealized_pnl_usd"))
        if isinstance(position_pricing, dict)
        else _safe_float(hb.get("unrealized_pnl_usd"))
    )
    total_pnl = realized_pnl + unrealized_pnl

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
            "unrealized_pnl_usd": unrealized_pnl,
        },
        "mode": "paper",
        "live_gate": "blocked_human_only",
        "places_real_order": False,
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
            "device": str(trainer.get("device") or ""),
            "gpu_name": str(trainer.get("gpu_name") or ""),
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
            "positions_preview": positions_enriched[:5],
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
            "device": str(trainer.get("device") or ""),
            "gpu_name": str(trainer.get("gpu_name") or ""),
            "cuda_active": bool(trainer.get("cuda_active")),
            "training_steps_total": _safe_int(trainer.get("training_steps_total")),
            "training_steps_last_hour": _safe_int(trainer.get("training_steps_last_hour")),
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
