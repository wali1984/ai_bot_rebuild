"""Monitoring endpoints — read-only observability layer.

These endpoints expose system observability data for authenticated users who can
see the Monitor Center page.
They never mutate any state, place orders, or restart services.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

from app.auth.security import require_auth
from app.auth.users import UserRecord

router = APIRouter(prefix="/admin/monitoring", tags=["v2-admin-monitoring"])


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _repo_root() -> Path:
    return Path(os.environ.get("V2_REPO_ROOT", "/home/wali/Desktop/AI BOT REBUILD"))


def _require_monitoring_reader(user: UserRecord = Depends(require_auth)) -> UserRecord:
    return user


# Known trader routes with their surfaces and expected owners
_KNOWN_ROUTES = [
    {"path": "/", "surface": "public", "owner": "landing", "expected": True},
    {"path": "/status", "surface": "public", "owner": "status", "expected": True},
    {"path": "/login", "surface": "public", "owner": "auth", "expected": True},
    {"path": "/markets", "surface": "public/app", "owner": "market-screener", "expected": True},
    {"path": "/market/:symbol", "surface": "public/app", "owner": "market-detail", "expected": True},
    {"path": "/dashboard", "surface": "app", "owner": "mission-control", "expected": True},
    {"path": "/trade", "surface": "app", "owner": "trade-terminal", "expected": True},
    {"path": "/derivatives", "surface": "app", "owner": "liquidation-bridge", "expected": True},
    {"path": "/signals", "surface": "app", "owner": "signals", "expected": True},
    {"path": "/ai-predictions", "surface": "app", "owner": "trainer-prediction-monitor", "expected": True},
    {"path": "/portfolio", "surface": "app", "owner": "positions", "expected": True},
    {"path": "/portfolio/executions", "surface": "app", "owner": "executions", "expected": True},
    {"path": "/portfolio/history", "surface": "app", "owner": "history", "expected": True},
    {"path": "/backtests", "surface": "app", "owner": "strategy-backtesting", "expected": True},
    {"path": "/backtests/replay", "surface": "app", "owner": "replay", "expected": True},
    {"path": "/research", "surface": "app", "owner": "market-intelligence", "expected": True},
    {"path": "/research/technical-analysis", "surface": "app", "owner": "technical-analysis", "expected": True},
    {"path": "/alerts", "surface": "app", "owner": "alerts", "expected": True},
    # Consolidated admin IA (canonical paths/owners; the legacy paths
    # /admin/ingestors, /admin/trainer, /admin/orchestrator now redirect —
    # see MERGED_LEGACY_PATHS in v2/frontend/src/pages/productNavigation.ts).
    {"path": "/admin", "surface": "admin", "owner": "admin-overview", "expected": True},
    {"path": "/admin/data", "surface": "admin", "owner": "admin-data", "expected": True},
    {"path": "/admin/intelligence", "surface": "admin", "owner": "admin-intelligence", "expected": True},
    {"path": "/admin/model-state", "surface": "admin", "owner": "admin-model-state", "expected": True},
    {"path": "/admin/orchestration", "surface": "admin", "owner": "admin-orchestration", "expected": True},
    {"path": "/admin/risk", "surface": "admin", "owner": "admin-risk", "expected": True},
    {"path": "/admin/execution", "surface": "admin", "owner": "admin-execution", "expected": True},
    {"path": "/admin/exchanges", "surface": "admin", "owner": "admin-exchanges", "expected": True},
    {"path": "/admin/config", "surface": "admin", "owner": "admin-config", "expected": True},
    {"path": "/admin/traders", "surface": "admin", "owner": "strategy-admin", "expected": True},
    {"path": "/admin/reports", "surface": "admin", "owner": "admin-reports", "expected": True},
    {"path": "/admin/tools", "surface": "admin", "owner": "admin-tools", "expected": True},
    {"path": "/admin/logs", "surface": "admin", "owner": "admin-logs", "expected": True},
    {"path": "/admin/audit", "surface": "superadmin", "owner": "admin-audit", "expected": True},
]

# Known data surfaces with expected sources
_DATA_SURFACES: list[dict[str, Any]] = [
    {"surface": "market_overview", "endpoint": "/api/v2/market/overview", "source_type": "api", "owner": "market-contracts"},
    {"surface": "market_tickers", "endpoint": "/api/v2/market/tickers/{symbol}", "source_type": "api", "owner": "market-contracts"},
    {"surface": "market_derivatives", "endpoint": "/api/v2/market/derivatives", "source_type": "api", "owner": "market-contracts"},
    {"surface": "signals", "endpoint": "/api/v2/signals", "source_type": "repository", "owner": "market-contracts"},
    {"surface": "portfolio", "endpoint": "/api/v2/portfolio", "source_type": "repository", "owner": "market-contracts"},
    {"surface": "ai_predictions", "endpoint": "/api/v2/ai/predictions", "source_type": "api", "owner": "trainer"},
    {"surface": "trainer_prediction", "endpoint": "/api/v2/trainer/prediction", "source_type": "api", "owner": "trainer"},
    {"surface": "alerts", "endpoint": "/api/v2/alerts", "source_type": "repository", "owner": "alerts-contracts"},
    {"surface": "public_status", "endpoint": "/api/v2/public/status", "source_type": "api", "owner": "public-status"},
    {"surface": "realtime_manifest", "endpoint": "/api/v2/realtime/manifest", "source_type": "static_snapshot", "owner": "market-contracts"},
    {"surface": "data_health", "endpoint": "/api/v2/data-health", "source_type": "api", "owner": "market-contracts"},
    {"surface": "backtests", "endpoint": "/api/v2/backtests", "source_type": "unavailable", "owner": "market-contracts"},
    {"surface": "research_context", "endpoint": "/api/v2/research/context", "source_type": "unavailable", "owner": "market-contracts"},
]


@router.get("/routes")
async def get_monitoring_routes(_: UserRecord = Depends(_require_monitoring_reader)) -> dict[str, Any]:
    """Return all known application routes with surface and ownership metadata."""
    return {
        "routes": _KNOWN_ROUTES,
        "total": len(_KNOWN_ROUTES),
        "timestamp": _utc_now(),
        "source": "/api/admin/monitoring/routes",
        "source_type": "static_snapshot",
    }


@router.get("/data-surfaces")
async def get_monitoring_data_surfaces(_: UserRecord = Depends(_require_monitoring_reader)) -> dict[str, Any]:
    """Return all known data surfaces with endpoint and source type metadata."""
    return {
        "surfaces": _DATA_SURFACES,
        "total": len(_DATA_SURFACES),
        "connected": sum(1 for s in _DATA_SURFACES if s["source_type"] != "unavailable"),
        "unavailable": sum(1 for s in _DATA_SURFACES if s["source_type"] == "unavailable"),
        "timestamp": _utc_now(),
        "source": "/api/admin/monitoring/data-surfaces",
        "source_type": "static_snapshot",
    }


@router.get("/realtime-streams")
async def get_monitoring_realtime_streams(_: UserRecord = Depends(_require_monitoring_reader)) -> dict[str, Any]:
    """Return status of known realtime data streams."""
    streams = [
        {"name": "Binance USD-M Ticker WS", "type": "websocket", "status": "check_required", "endpoint": "wss://fstream.binance.com"},
        {"name": "Market Overview Polling", "type": "api_poll", "status": "active", "endpoint": "/api/v2/market/overview", "interval_ms": 30000},
        {"name": "Signals Poll", "type": "api_poll", "status": "active", "endpoint": "/api/v2/signals", "interval_ms": 10000},
        {"name": "Portfolio Poll", "type": "api_poll", "status": "active", "endpoint": "/api/v2/portfolio", "interval_ms": 15000},
        {"name": "AI Predictions Poll", "type": "api_poll", "status": "active", "endpoint": "/api/v2/ai/predictions", "interval_ms": 30000},
        {"name": "Data Health Poll", "type": "api_poll", "status": "active", "endpoint": "/api/v2/data-health", "interval_ms": 30000},
    ]
    return {
        "streams": streams,
        "total": len(streams),
        "active": sum(1 for s in streams if s["status"] == "active"),
        "timestamp": _utc_now(),
        "source": "/api/admin/monitoring/realtime-streams",
        "source_type": "static_snapshot",
    }


@router.get("/frontend-errors")
async def get_monitoring_frontend_errors(_: UserRecord = Depends(_require_monitoring_reader)) -> dict[str, Any]:
    """Return recent frontend error events (stub — no persistent frontend error log yet)."""
    return {
        "errors": [],
        "total": 0,
        "note": "Frontend error capture not yet wired to persistent backend log. Implement ErrorBoundary → POST /api/admin/monitoring/frontend-errors",
        "timestamp": _utc_now(),
        "source": "/api/admin/monitoring/frontend-errors",
        "source_type": "unavailable",
    }


@router.get("/backend-errors")
async def get_monitoring_backend_errors(_: UserRecord = Depends(_require_monitoring_reader)) -> dict[str, Any]:
    """Return recent backend error events from the error log if available."""
    errors: list[dict[str, Any]] = []
    log_path = _repo_root() / "v2" / "backend" / "logs" / "errors.jsonl"
    try:
        if log_path.exists():
            lines = log_path.read_text(encoding="utf-8").splitlines()
            import json
            for line in lines[-50:]:
                try:
                    errors.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        pass
    return {
        "errors": errors,
        "total": len(errors),
        "source_path": str(log_path),
        "timestamp": _utc_now(),
        "source": "/api/admin/monitoring/backend-errors",
        "source_type": "repository" if log_path.exists() else "unavailable",
    }


@router.get("/test-status")
async def get_monitoring_test_status(_: UserRecord = Depends(_require_monitoring_reader)) -> dict[str, Any]:
    """Return last known test run status."""
    result_path = _repo_root() / "v2" / "backend" / ".test_status.json"
    result: dict[str, Any] | None = None
    try:
        if result_path.exists():
            import json
            result = json.loads(result_path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {
        "last_run": result,
        "timestamp": _utc_now(),
        "source": "/api/admin/monitoring/test-status",
        "source_type": "repository" if result else "unavailable",
        "note": "Run `pytest` and capture results to .test_status.json to populate this endpoint",
    }


@router.get("/build-status")
async def get_monitoring_build_status(_: UserRecord = Depends(_require_monitoring_reader)) -> dict[str, Any]:
    """Return last known frontend build status."""
    dist_path = _repo_root() / "v2" / "frontend" / "dist"
    build_exists = dist_path.exists()
    index_exists = (dist_path / "index.html").exists() if build_exists else False
    return {
        "dist_exists": build_exists,
        "index_exists": index_exists,
        "dist_path": str(dist_path),
        "status": "built" if index_exists else "not_built",
        "timestamp": _utc_now(),
        "source": "/api/admin/monitoring/build-status",
        "source_type": "repository",
    }


@router.get("/data-contract-violations")
async def get_monitoring_data_contract_violations(_: UserRecord = Depends(_require_monitoring_reader)) -> dict[str, Any]:
    """Return data contract violations captured by the frontend (stub)."""
    return {
        "violations": [],
        "total": 0,
        "note": "Data contract violation capture not yet wired. Implement frontend → POST /api/admin/monitoring/data-contract-violations",
        "timestamp": _utc_now(),
        "source": "/api/admin/monitoring/data-contract-violations",
        "source_type": "unavailable",
    }
