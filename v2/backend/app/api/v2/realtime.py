"""Enterprise realtime bootstrap and shared WebSocket contract."""

from __future__ import annotations

import asyncio
import contextlib
import copy
import json
import os
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Lock
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from app.api.v2._common import get_redis
from app.api.v2.market_contracts import (
    _cancel_websocket_disconnect_task,
    _close_websocket_for_service_restart,
    _readonly_resource_resolve_payload,
    _readonly_resource_ws_payload,
    _safe_readonly_resource_target,
    _wait_for_next_websocket_iteration,
    _watch_websocket_disconnect,
    _websocket_is_connected,
)
from app.services.realtime import build_enterprise_bootstrap, build_ui_snapshot
from app.services.realtime.resource_registry import resource_contracts, resource_names

router = APIRouter(prefix="/realtime", tags=["enterprise-realtime"])
stream_router = APIRouter(prefix="/stream", tags=["enterprise-stream"])
DISPLAY_TZ = ZoneInfo("America/New_York")
ENTERPRISE_REALTIME_BOOTSTRAP_TIMEOUT_SECONDS = float(
    os.environ.get("ALPHAFORGE_ENTERPRISE_REALTIME_BOOTSTRAP_TIMEOUT_SECONDS", "1.0")
)
ENTERPRISE_REALTIME_SNAPSHOT_TIMEOUT_SECONDS = float(
    os.environ.get("ALPHAFORGE_ENTERPRISE_REALTIME_SNAPSHOT_TIMEOUT_SECONDS", "0.75")
)
ENTERPRISE_REALTIME_MAX_READONLY_PATHS = int(
    os.environ.get("ALPHAFORGE_ENTERPRISE_REALTIME_MAX_READONLY_PATHS", "12")
)
ENTERPRISE_REALTIME_EXECUTOR_WORKERS = int(
    os.environ.get("ALPHAFORGE_ENTERPRISE_REALTIME_EXECUTOR_WORKERS", "2")
)
ENTERPRISE_REALTIME_CACHE_TTL_SECONDS = float(
    os.environ.get("ALPHAFORGE_ENTERPRISE_REALTIME_CACHE_TTL_SECONDS", "2.0")
)
ENTERPRISE_REALTIME_STALE_CACHE_TTL_SECONDS = float(
    os.environ.get("ALPHAFORGE_ENTERPRISE_REALTIME_STALE_CACHE_TTL_SECONDS", "60.0")
)
ENTERPRISE_REALTIME_WS_SEND_TIMEOUT_SECONDS = float(
    os.environ.get("ALPHAFORGE_ENTERPRISE_REALTIME_WS_SEND_TIMEOUT_SECONDS", "0.75")
)
ENTERPRISE_REALTIME_MAX_ACTIVE_WEBSOCKETS = int(
    os.environ.get("ALPHAFORGE_ENTERPRISE_REALTIME_MAX_ACTIVE_WEBSOCKETS", "32")
)
ENTERPRISE_REALTIME_MAX_ACTIVE_WEBSOCKETS_PER_CLIENT = int(
    os.environ.get("ALPHAFORGE_ENTERPRISE_REALTIME_MAX_ACTIVE_WEBSOCKETS_PER_CLIENT", "8")
)
ENTERPRISE_REALTIME_SSE_INTERVAL_SECONDS = float(
    os.environ.get("ALPHAFORGE_ENTERPRISE_REALTIME_SSE_INTERVAL_SECONDS", "2.0")
)
ENTERPRISE_REALTIME_SSE_MAX_BOOTSTRAP_EVENTS = int(
    os.environ.get("ALPHAFORGE_ENTERPRISE_REALTIME_SSE_MAX_BOOTSTRAP_EVENTS", "0")
)

_REALTIME_EXECUTOR = ThreadPoolExecutor(
    max_workers=max(1, ENTERPRISE_REALTIME_EXECUTOR_WORKERS),
    thread_name_prefix="enterprise-realtime",
)
_CACHE_LOCK = Lock()
_WEBSOCKET_LOCK = Lock()
_BOOTSTRAP_CACHE: dict[str, Any] | None = None
_BOOTSTRAP_CACHE_AT = 0.0
_BOOTSTRAP_INFLIGHT = False
_SNAPSHOT_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_SNAPSHOT_INFLIGHT: set[str] = set()
_REDIS_AVAILABLE_CACHE: tuple[float, bool] = (0.0, False)
_ACTIVE_REALTIME_WEBSOCKETS_BY_CLIENT: dict[str, int] = {}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _display_time_et() -> str:
    return datetime.now(DISPLAY_TZ).isoformat(timespec="seconds")


def _copy_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(payload)


def _mark_redis_available(value: bool) -> None:
    global _REDIS_AVAILABLE_CACHE
    with _CACHE_LOCK:
        _REDIS_AVAILABLE_CACHE = (time.monotonic(), bool(value))


def _cached_redis_available() -> bool:
    with _CACHE_LOCK:
        observed_at, value = _REDIS_AVAILABLE_CACHE
    return bool(value) and time.monotonic() - observed_at <= ENTERPRISE_REALTIME_STALE_CACHE_TTL_SECONDS


def _active_websocket_counts() -> tuple[int, dict[str, int]]:
    with _WEBSOCKET_LOCK:
        by_client = dict(_ACTIVE_REALTIME_WEBSOCKETS_BY_CLIENT)
    return sum(by_client.values()), by_client


def _websocket_client_id(websocket: WebSocket) -> str:
    if websocket.client and websocket.client.host:
        return str(websocket.client.host)
    return "unknown"


def _try_register_realtime_websocket(client_id: str) -> tuple[bool, int, int]:
    max_total = max(1, ENTERPRISE_REALTIME_MAX_ACTIVE_WEBSOCKETS)
    max_client = max(1, ENTERPRISE_REALTIME_MAX_ACTIVE_WEBSOCKETS_PER_CLIENT)
    with _WEBSOCKET_LOCK:
        total = sum(_ACTIVE_REALTIME_WEBSOCKETS_BY_CLIENT.values())
        client_count = _ACTIVE_REALTIME_WEBSOCKETS_BY_CLIENT.get(client_id, 0)
        if total >= max_total or client_count >= max_client:
            return False, total, client_count
        _ACTIVE_REALTIME_WEBSOCKETS_BY_CLIENT[client_id] = client_count + 1
        return True, total + 1, client_count + 1


def _unregister_realtime_websocket(client_id: str) -> None:
    with _WEBSOCKET_LOCK:
        current = _ACTIVE_REALTIME_WEBSOCKETS_BY_CLIENT.get(client_id, 0)
        if current <= 1:
            _ACTIVE_REALTIME_WEBSOCKETS_BY_CLIENT.pop(client_id, None)
        else:
            _ACTIVE_REALTIME_WEBSOCKETS_BY_CLIENT[client_id] = current - 1


def _minimal_snapshot_payload(resource: str, reason: str) -> dict[str, Any]:
    generated_at_utc = _utc_now()
    generated_at_et = _display_time_et()
    return {
        "schema_version": "enterprise_ui_snapshot_v1",
        "resource": resource,
        "generated_utc": generated_at_utc,
        "generated_at_utc": generated_at_utc,
        "display_time_et": generated_at_et,
        "generated_at_et": generated_at_et,
        "source_timezone": "UTC",
        "display_timezone": "America/New_York",
        "source": "realtime_api_bounded_fallback",
        "source_type": "degraded_fallback",
        "source_keys": [],
        "staleness_seconds": None,
        "freshness_status": "degraded",
        "canonical_owner": f"/api/v2/ui/{resource.replace('_', '-')}",
        "data_quality": "degraded",
        "data_quality_status": "degraded",
        "missing_sections": ["redis_materialized_view"],
        "error_sections": ["bounded_realtime_builder"],
        "last_good_payload_used": False,
        "payload": {
            "schema_version": f"enterprise_{resource}_snapshot_fallback_v1",
            "status": "degraded",
            "warning": reason,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        },
        "live_gate": "blocked_human_only",
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "warnings": [reason],
    }


def _minimal_bootstrap_payload(reason: str) -> dict[str, Any]:
    generated_at_utc = _utc_now()
    generated_at_et = _display_time_et()
    resources = {
        name: _minimal_snapshot_payload(name, reason)
        for name in resource_names()
    }
    portfolio_payload = resources.get("portfolio", {}).get("payload", {})
    dashboard_payload = resources.get("dashboard", {}).get("payload", {})
    risk_payload = resources.get("risk", {}).get("payload", {})
    trainer_payload = resources.get("ai_brain", {}).get("payload", {})
    providers_payload = resources.get("providers", {}).get("payload", {})
    markets_payload = resources.get("markets", {}).get("payload", {})
    return {
        "schema_version": "enterprise_realtime_bootstrap_v1",
        "generated_utc": generated_at_utc,
        "generated_at_utc": generated_at_utc,
        "display_time_et": generated_at_et,
        "generated_at_et": generated_at_et,
        "display_timezone": "America/New_York",
        "source": "realtime_api_bounded_fallback",
        "source_type": "degraded_fallback",
        "staleness_seconds": None,
        "freshness_status": "degraded",
        "canonical_owner": "/api/v2/realtime/bootstrap",
        "data_quality_status": "degraded",
        "auth": {"required_for_controls": True, "public_routes": ["login", "health"]},
        "portfolio": portfolio_payload,
        "paper": dashboard_payload.get("paper", {}),
        "risk": risk_payload,
        "trainer": trainer_payload,
        "signals": {},
        "providers": providers_payload,
        "ingestors": providers_payload,
        "markets": markets_payload,
        "live_canary": risk_payload.get("live_canary", {}),
        "alerts": {},
        "ui_hints": {
            "default_pnl_display": "usd_and_percent",
            "show_stale_degraded_state": True,
            "live_controls_disabled": True,
        },
        "resources": resources,
        "status": "degraded",
        "warnings": [reason],
        "live_gate": "blocked_human_only",
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _with_cache_warning(payload: dict[str, Any], warning: str) -> dict[str, Any]:
    cloned = _copy_payload(payload)
    warnings = cloned.setdefault("warnings", [])
    if isinstance(warnings, list) and warning not in warnings:
        warnings.append(warning)
    cloned["last_good_payload_used"] = True
    cloned["cache_status"] = "stale_last_good"
    return cloned


def _build_bootstrap_uncached() -> dict[str, Any]:
    client = get_redis()
    _mark_redis_available(client is not None)
    return build_enterprise_bootstrap(client)


def _build_snapshot_uncached(resource: str) -> dict[str, Any]:
    client = get_redis()
    _mark_redis_available(client is not None)
    return build_ui_snapshot(client, resource)


def _cached_bootstrap(max_age_seconds: float) -> dict[str, Any] | None:
    with _CACHE_LOCK:
        if _BOOTSTRAP_CACHE is None:
            return None
        if time.monotonic() - _BOOTSTRAP_CACHE_AT > max_age_seconds:
            return None
        return _copy_payload(_BOOTSTRAP_CACHE)


def _remember_bootstrap(payload: dict[str, Any]) -> None:
    global _BOOTSTRAP_CACHE, _BOOTSTRAP_CACHE_AT
    with _CACHE_LOCK:
        _BOOTSTRAP_CACHE = _copy_payload(payload)
        _BOOTSTRAP_CACHE_AT = time.monotonic()


def _submit_bootstrap_build() -> Future[dict[str, Any]] | None:
    global _BOOTSTRAP_INFLIGHT
    with _CACHE_LOCK:
        if _BOOTSTRAP_INFLIGHT:
            return None
        _BOOTSTRAP_INFLIGHT = True
    future = _REALTIME_EXECUTOR.submit(_build_bootstrap_uncached)

    def _done(done: Future[dict[str, Any]]) -> None:
        global _BOOTSTRAP_INFLIGHT
        try:
            payload = done.result()
            if isinstance(payload, dict):
                _remember_bootstrap(payload)
        except Exception:
            pass
        finally:
            with _CACHE_LOCK:
                _BOOTSTRAP_INFLIGHT = False

    future.add_done_callback(_done)
    return future


def _cached_snapshot(resource: str, max_age_seconds: float) -> dict[str, Any] | None:
    with _CACHE_LOCK:
        cached = _SNAPSHOT_CACHE.get(resource)
        if cached is None:
            return None
        cached_at, payload = cached
        if time.monotonic() - cached_at > max_age_seconds:
            return None
        return _copy_payload(payload)


def _remember_snapshot(resource: str, payload: dict[str, Any]) -> None:
    with _CACHE_LOCK:
        _SNAPSHOT_CACHE[resource] = (time.monotonic(), _copy_payload(payload))


def _submit_snapshot_build(resource: str) -> Future[dict[str, Any]] | None:
    with _CACHE_LOCK:
        if resource in _SNAPSHOT_INFLIGHT:
            return None
        _SNAPSHOT_INFLIGHT.add(resource)
    future = _REALTIME_EXECUTOR.submit(_build_snapshot_uncached, resource)

    def _done(done: Future[dict[str, Any]]) -> None:
        try:
            payload = done.result()
            if isinstance(payload, dict):
                _remember_snapshot(resource, payload)
        except Exception:
            pass
        finally:
            with _CACHE_LOCK:
                _SNAPSHOT_INFLIGHT.discard(resource)

    future.add_done_callback(_done)
    return future


async def _await_realtime_future(future: Future[dict[str, Any]], *, timeout: float) -> dict[str, Any]:
    return await asyncio.wait_for(
        asyncio.shield(asyncio.wrap_future(future)),
        timeout=max(0.1, float(timeout)),
    )


async def _build_bootstrap_bounded() -> dict[str, Any]:
    fresh = _cached_bootstrap(ENTERPRISE_REALTIME_CACHE_TTL_SECONDS)
    if fresh is not None:
        return fresh
    future = _submit_bootstrap_build()
    if future is None:
        stale = _cached_bootstrap(ENTERPRISE_REALTIME_STALE_CACHE_TTL_SECONDS)
        if stale is not None:
            return _with_cache_warning(stale, "Enterprise realtime bootstrap build already in progress")
        return _minimal_bootstrap_payload("Enterprise realtime bootstrap build already in progress")
    try:
        payload = await _await_realtime_future(
            future,
            timeout=ENTERPRISE_REALTIME_BOOTSTRAP_TIMEOUT_SECONDS,
        )
        _remember_bootstrap(payload)
        return payload
    except asyncio.TimeoutError:
        stale = _cached_bootstrap(ENTERPRISE_REALTIME_STALE_CACHE_TTL_SECONDS)
        if stale is not None:
            return _with_cache_warning(stale, "Enterprise realtime bootstrap exceeded bounded read timeout")
        return _minimal_bootstrap_payload("Enterprise realtime bootstrap exceeded bounded read timeout")
    except Exception as exc:
        stale = _cached_bootstrap(ENTERPRISE_REALTIME_STALE_CACHE_TTL_SECONDS)
        if stale is not None:
            return _with_cache_warning(stale, f"Enterprise realtime bootstrap unavailable: {type(exc).__name__}")
        return _minimal_bootstrap_payload(f"Enterprise realtime bootstrap unavailable: {type(exc).__name__}")


async def _build_snapshot_bounded(resource: str) -> dict[str, Any]:
    fresh = _cached_snapshot(resource, ENTERPRISE_REALTIME_CACHE_TTL_SECONDS)
    if fresh is not None:
        return fresh
    future = _submit_snapshot_build(resource)
    if future is None:
        stale = _cached_snapshot(resource, ENTERPRISE_REALTIME_STALE_CACHE_TTL_SECONDS)
        if stale is not None:
            return _with_cache_warning(stale, "Enterprise realtime snapshot build already in progress")
        return _minimal_snapshot_payload(resource, "Enterprise realtime snapshot build already in progress")
    try:
        payload = await _await_realtime_future(
            future,
            timeout=ENTERPRISE_REALTIME_SNAPSHOT_TIMEOUT_SECONDS,
        )
        _remember_snapshot(resource, payload)
        return payload
    except asyncio.TimeoutError:
        stale = _cached_snapshot(resource, ENTERPRISE_REALTIME_STALE_CACHE_TTL_SECONDS)
        if stale is not None:
            return _with_cache_warning(stale, "Enterprise realtime snapshot exceeded bounded read timeout")
        return _minimal_snapshot_payload(resource, "Enterprise realtime snapshot exceeded bounded read timeout")
    except Exception as exc:
        stale = _cached_snapshot(resource, ENTERPRISE_REALTIME_STALE_CACHE_TTL_SECONDS)
        if stale is not None:
            return _with_cache_warning(stale, f"Enterprise realtime snapshot unavailable: {type(exc).__name__}")
        return _minimal_snapshot_payload(resource, f"Enterprise realtime snapshot unavailable: {type(exc).__name__}")


def _clear_realtime_caches_for_tests() -> None:
    global _BOOTSTRAP_CACHE, _BOOTSTRAP_CACHE_AT, _BOOTSTRAP_INFLIGHT, _REDIS_AVAILABLE_CACHE
    with _CACHE_LOCK:
        _BOOTSTRAP_CACHE = None
        _BOOTSTRAP_CACHE_AT = 0.0
        _BOOTSTRAP_INFLIGHT = False
        _SNAPSHOT_CACHE.clear()
        _SNAPSHOT_INFLIGHT.clear()
        _REDIS_AVAILABLE_CACHE = (0.0, False)


@router.get("/bootstrap")
async def get_realtime_bootstrap() -> dict[str, Any]:
    return await _build_bootstrap_bounded()


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
    redis_available = _cached_redis_available()
    active_websocket_count, active_websocket_count_by_client = _active_websocket_counts()
    return {
        "schema_version": "enterprise_realtime_health_v1",
        "generated_utc": _utc_now(),
        "display_time_et": _display_time_et(),
        "status": "ok",
        "redis_available": redis_available,
        "redis_check": "cached_nonblocking",
        "websocket_endpoint": "/api/v2/realtime/ws",
        "resource_count": len(resource_names()),
        "one_socket_per_session": True,
        "readonly_path_multiplexing": True,
        "active_websocket_count": active_websocket_count,
        "active_websocket_count_by_client": active_websocket_count_by_client,
        "max_active_websocket_count": max(1, ENTERPRISE_REALTIME_MAX_ACTIVE_WEBSOCKETS),
        "max_active_websocket_count_per_client": max(
            1,
            ENTERPRISE_REALTIME_MAX_ACTIVE_WEBSOCKETS_PER_CLIENT,
        ),
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
    }


STREAM_RESOURCE_GROUPS: dict[str, tuple[str, ...]] = {
    "runtime": (
        "dashboard",
        "portfolio",
        "trader_cockpit",
        "system_health",
    ),
    "trading": (
        "dashboard",
        "portfolio",
        "trader_cockpit",
        "risk",
        "markets",
    ),
    "providers": (
        "providers",
        "system_health",
    ),
    "trainer": (
        "ai_brain",
        "providers",
    ),
    "risk": (
        "risk",
        "portfolio",
        "trader_cockpit",
    ),
}

STREAM_EVENT_NAMES: dict[str, tuple[str, ...]] = {
    "runtime": (
        "portfolio_update",
        "paper_update",
        "real_account_update",
        "position_update",
        "a_plus_inventory_update",
        "probation_gate_update",
        "live_canary_update",
        "risk_update",
        "trainer_update",
        "provider_update",
        "ingestor_update",
        "squeeze_risk_update",
        "hedge_update",
        "liquidation_buffer_update",
    ),
    "trading": (
        "portfolio_update",
        "paper_update",
        "position_update",
        "a_plus_inventory_update",
        "probation_gate_update",
        "live_canary_update",
        "squeeze_risk_update",
        "hedge_update",
        "liquidation_buffer_update",
    ),
    "providers": (
        "provider_update",
        "ingestor_update",
    ),
    "trainer": (
        "trainer_update",
        "provider_update",
    ),
    "risk": (
        "risk_update",
        "live_canary_update",
        "hedge_update",
        "liquidation_buffer_update",
    ),
}


def _sse_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }


def _sse_event(event: str, payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, separators=(",", ":"), default=str)
    return f"event: {event}\ndata: {encoded}\n\n"


def _stream_resource_staleness_seconds(resource: dict[str, Any]) -> float | None:
    value = resource.get("staleness_seconds")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or abs(parsed) == float("inf"):
        return None
    return max(0.0, parsed)


def _stream_freshness_status(staleness_seconds: float | None, resources: dict[str, Any]) -> str:
    if not resources:
        return "missing"
    if staleness_seconds is None:
        return "unknown"
    if staleness_seconds <= 30:
        return "fresh"
    if staleness_seconds <= 300:
        return "degraded"
    return "stale"


def _stream_data_quality_status(resources: dict[str, Any], freshness_status: str) -> str:
    if not resources:
        return "missing"
    qualities = {
        str(resource.get("data_quality_status") or resource.get("data_quality") or "unknown").lower()
        for resource in resources.values()
        if isinstance(resource, dict)
    }
    if "missing" in qualities or "invalid" in qualities:
        return "missing"
    if freshness_status == "stale":
        return "stale"
    if "degraded" in qualities or "partial" in qualities:
        return "partial"
    if freshness_status == "fresh" and qualities <= {"valid", "fresh"}:
        return "fresh"
    if "valid" in qualities or "fresh" in qualities:
        return "partial"
    return "unknown"


def _stream_resource_sources(resources: dict[str, Any]) -> list[str]:
    sources: list[str] = []
    for resource in resources.values():
        if not isinstance(resource, dict):
            continue
        source = resource.get("source")
        if source is None:
            continue
        text = str(source).strip()
        if text and text not in sources:
            sources.append(text)
    return sources


async def _stream_group_payload(stream_name: str, sequence: int) -> dict[str, Any]:
    resources: dict[str, Any] = {}
    for resource in STREAM_RESOURCE_GROUPS[stream_name]:
        resources[resource] = await _build_snapshot_bounded(resource)
    resource_staleness = [
        age
        for resource in resources.values()
        if isinstance(resource, dict)
        for age in [_stream_resource_staleness_seconds(resource)]
        if age is not None
    ]
    staleness_seconds = max(resource_staleness) if resource_staleness else None
    freshness_status = _stream_freshness_status(staleness_seconds, resources)
    generated_at_utc = _utc_now()
    generated_at_et = _display_time_et()
    return {
        "schema_version": "enterprise_runtime_stream_event_v1",
        "stream": stream_name,
        "sequence": sequence,
        "generated_utc": generated_at_utc,
        "generated_at_utc": generated_at_utc,
        "display_time_et": generated_at_et,
        "generated_at_et": generated_at_et,
        "source": f"enterprise_realtime_stream:{stream_name}",
        "source_resource_count": len(resources),
        "source_resources": list(resources.keys()),
        "source_snapshot_keys": _stream_resource_sources(resources),
        "staleness_seconds": staleness_seconds,
        "freshness_status": freshness_status,
        "canonical_owner": f"/api/v2/stream/{stream_name}",
        "data_quality_status": _stream_data_quality_status(resources, freshness_status),
        "event_names": list(STREAM_EVENT_NAMES[stream_name]),
        "resources": resources,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
    }


def _stream_response(
    stream_name: str,
    *,
    once: bool,
    interval_seconds: float | None,
) -> StreamingResponse:
    interval = max(
        1.0,
        min(30.0, interval_seconds or ENTERPRISE_REALTIME_SSE_INTERVAL_SECONDS),
    )
    max_events = 1 if once else max(0, ENTERPRISE_REALTIME_SSE_MAX_BOOTSTRAP_EVENTS)

    async def _events() -> Any:
        sequence = 0
        yield ": enterprise runtime stream connected\n\n"
        while True:
            sequence += 1
            payload = await _stream_group_payload(stream_name, sequence)
            yield _sse_event(f"{stream_name}_update", payload)
            if max_events and sequence >= max_events:
                break
            await asyncio.sleep(interval)

    return StreamingResponse(
        _events(),
        media_type="text/event-stream",
        headers=_sse_headers(),
    )


@stream_router.get("/runtime")
async def stream_runtime(once: bool = False, interval_seconds: float | None = None) -> StreamingResponse:
    return _stream_response("runtime", once=once, interval_seconds=interval_seconds)


@stream_router.get("/trading")
async def stream_trading(once: bool = False, interval_seconds: float | None = None) -> StreamingResponse:
    return _stream_response("trading", once=once, interval_seconds=interval_seconds)


@stream_router.get("/providers")
async def stream_providers(once: bool = False, interval_seconds: float | None = None) -> StreamingResponse:
    return _stream_response("providers", once=once, interval_seconds=interval_seconds)


@stream_router.get("/trainer")
async def stream_trainer(once: bool = False, interval_seconds: float | None = None) -> StreamingResponse:
    return _stream_response("trainer", once=once, interval_seconds=interval_seconds)


@stream_router.get("/risk")
async def stream_risk(once: bool = False, interval_seconds: float | None = None) -> StreamingResponse:
    return _stream_response("risk", once=once, interval_seconds=interval_seconds)


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
        if len(selected) >= max(1, ENTERPRISE_REALTIME_MAX_READONLY_PATHS):
            break
    return selected


async def _send_json_bounded(websocket: WebSocket, payload: dict[str, Any]) -> None:
    try:
        await asyncio.wait_for(
            websocket.send_json(payload),
            timeout=max(0.1, ENTERPRISE_REALTIME_WS_SEND_TIMEOUT_SECONDS),
        )
    except (WebSocketDisconnect, RuntimeError, asyncio.TimeoutError):
        with contextlib.suppress(Exception):
            await websocket.close(code=1011)
        raise


@router.websocket("/ws")
async def realtime_websocket(websocket: WebSocket) -> None:
    client_id = _websocket_client_id(websocket)
    registered, total_count, client_count = _try_register_realtime_websocket(client_id)
    await websocket.accept()
    if not registered:
        with contextlib.suppress(Exception):
            await _send_json_bounded(websocket, {
                "type": "capacity_limit",
                "generated_utc": _utc_now(),
                "display_time_et": _display_time_et(),
                "payload": {
                    "status": "degraded",
                    "reason": "enterprise_realtime_websocket_capacity_limit",
                    "active_websocket_count": total_count,
                    "active_websocket_count_for_client": client_count,
                    "max_active_websocket_count": max(1, ENTERPRISE_REALTIME_MAX_ACTIVE_WEBSOCKETS),
                    "max_active_websocket_count_per_client": max(
                        1,
                        ENTERPRISE_REALTIME_MAX_ACTIVE_WEBSOCKETS_PER_CLIENT,
                    ),
                    "routes_to_live": False,
                    "places_real_order": False,
                },
            })
        with contextlib.suppress(Exception):
            await websocket.close(code=1013)
        return
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
    last_path_send = time.monotonic()
    disconnect_task = asyncio.create_task(_watch_websocket_disconnect(websocket))
    try:
        bootstrap = await _build_bootstrap_bounded()
        await _send_json_bounded(websocket, {
            "type": "bootstrap",
            "sequence": sequence,
            "generated_utc": _utc_now(),
            "display_time_et": _display_time_et(),
            "payload": bootstrap,
        })
        while _websocket_is_connected(websocket) and not disconnect_task.done():
            for resource in resources:
                if disconnect_task.done():
                    break
                sequence += 1
                await _send_json_bounded(websocket, {
                    "type": "resource_delta",
                    "resource": resource,
                    "sequence": sequence,
                    "generated_utc": _utc_now(),
                    "display_time_et": _display_time_et(),
                    "payload": await _build_snapshot_bounded(resource),
                })
            now = time.monotonic()
            if (
                readonly_paths
                and not disconnect_task.done()
                and now - last_path_send >= path_interval_seconds
            ):
                last_path_send = now
                for path in readonly_paths:
                    if disconnect_task.done():
                        break
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
                    await _send_json_bounded(websocket, {
                        "type": "resource_path_delta",
                        "path": path,
                        "sequence": sequence,
                        "generated_utc": _utc_now(),
                        "display_time_et": _display_time_et(),
                        "payload": payload,
                    })
            wait_result = await _wait_for_next_websocket_iteration(interval_seconds, disconnect_task)
            if wait_result in {"shutdown", "disconnect"}:
                break
        if not disconnect_task.done():
            await _close_websocket_for_service_restart(websocket)
    except WebSocketDisconnect:
        return
    except (RuntimeError, asyncio.TimeoutError):
        return
    finally:
        _unregister_realtime_websocket(client_id)
        await _cancel_websocket_disconnect_task(disconnect_task)
