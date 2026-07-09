"""Enterprise realtime bootstrap and shared WebSocket contract."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.v2._common import get_redis
from app.api.v2.market_contracts import (
    _readonly_resource_resolve_payload,
    _readonly_resource_ws_payload,
    _safe_readonly_resource_target,
)
from app.services.realtime import build_enterprise_bootstrap, build_ui_snapshot
from app.services.realtime.resource_registry import resource_contracts, resource_names

router = APIRouter(prefix="/realtime", tags=["enterprise-realtime"])
DISPLAY_TZ = ZoneInfo("America/New_York")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _display_time_et() -> str:
    return datetime.now(DISPLAY_TZ).isoformat(timespec="seconds")


@router.get("/bootstrap")
async def get_realtime_bootstrap() -> dict[str, Any]:
    return build_enterprise_bootstrap(get_redis())


@router.get("/resources")
async def get_realtime_resources() -> dict[str, Any]:
    return {
        "schema_version": "enterprise_realtime_resources_v1",
        "generated_utc": _utc_now(),
        "display_time_et": _display_time_et(),
        "resources": resource_contracts(),
        "websocket_endpoint": "/api/v2/realtime/ws",
        "one_socket_per_session": True,
        "readonly_path_multiplexing": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


@router.get("/health")
async def get_realtime_health() -> dict[str, Any]:
    client = get_redis()
    return {
        "schema_version": "enterprise_realtime_health_v1",
        "generated_utc": _utc_now(),
        "display_time_et": _display_time_et(),
        "status": "ok" if client is not None else "degraded",
        "redis_available": client is not None,
        "websocket_endpoint": "/api/v2/realtime/ws",
        "resource_count": len(resource_names()),
        "one_socket_per_session": True,
        "readonly_path_multiplexing": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
    }


def _requested_resources(value: str | None) -> list[str]:
    if not value:
        return resource_names()
    requested = [item.strip().replace("-", "_") for item in value.split(",") if item.strip()]
    allowed = set(resource_names())
    selected = [item for item in requested if item in allowed]
    return selected or resource_names()


def _requested_readonly_paths(websocket: WebSocket) -> list[str]:
    raw_values: list[str] = []
    raw_values.extend(websocket.query_params.getlist("path"))
    paths_value = websocket.query_params.get("paths")
    if paths_value:
        raw_values.extend(item.strip() for item in paths_value.split(",") if item.strip())

    selected: list[str] = []
    seen: set[str] = set()
    for value in raw_values:
        target = _safe_readonly_resource_target(value)
        if target is None or target in seen:
            continue
        selected.append(target)
        seen.add(target)
        if len(selected) >= 40:
            break
    return selected


@router.websocket("/ws")
async def realtime_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        interval_ms = int(websocket.query_params.get("interval_ms", "2000"))
    except ValueError:
        interval_ms = 2000
    interval_seconds = max(1.0, min(30.0, interval_ms / 1000.0))
    try:
        path_interval_ms = int(websocket.query_params.get("path_interval_ms", "15000"))
    except ValueError:
        path_interval_ms = 15000
    path_interval_seconds = max(interval_seconds, min(120.0, max(5.0, path_interval_ms / 1000.0)))
    resources = _requested_resources(websocket.query_params.get("resources"))
    readonly_paths = _requested_readonly_paths(websocket)
    headers = {key.lower(): value for key, value in websocket.headers.items()}
    sequence = 0
    last_path_send = 0.0
    try:
        client = get_redis()
        bootstrap = build_enterprise_bootstrap(client)
        await websocket.send_json({
            "type": "bootstrap",
            "sequence": sequence,
            "generated_utc": _utc_now(),
            "display_time_et": _display_time_et(),
            "payload": bootstrap,
        })
        while True:
            client = get_redis()
            for resource in resources:
                sequence += 1
                await websocket.send_json({
                    "type": "resource_delta",
                    "resource": resource,
                    "sequence": sequence,
                    "generated_utc": _utc_now(),
                    "display_time_et": _display_time_et(),
                    "payload": build_ui_snapshot(client, resource),
                })
            now = time.monotonic()
            if readonly_paths and now - last_path_send >= path_interval_seconds:
                last_path_send = now
                for path in readonly_paths:
                    sequence += 1
                    started = time.monotonic()
                    try:
                        payload = await _readonly_resource_resolve_payload(path, headers)
                        payload = _readonly_resource_ws_payload(path, payload, started)
                    except Exception as exc:
                        payload = {
                            "data": None,
                            "source": path,
                            "source_type": "unavailable",
                            "endpoint": path,
                            "timestamp": _utc_now(),
                            "received_at": _utc_now(),
                            "lag_ms": round((time.monotonic() - started) * 1000),
                            "stale": True,
                            "missing_fields": ["resource"],
                            "warnings": [str(exc)],
                            "mode": "read_only",
                            "transport": "websocket",
                            "resource_path": path,
                        }
                    await websocket.send_json({
                        "type": "resource_path_delta",
                        "path": path,
                        "sequence": sequence,
                        "generated_utc": _utc_now(),
                        "display_time_et": _display_time_et(),
                        "payload": payload,
                    })
            await asyncio.sleep(interval_seconds)
    except WebSocketDisconnect:
        return
    except RuntimeError:
        return
