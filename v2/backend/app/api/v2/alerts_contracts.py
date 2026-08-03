"""Safe V2 alert contracts for public/trader surfaces.

Authenticated traders can manage paper/read-only alert records scoped by
trader_id and paper_account_id. This module does not deliver notifications,
call exchanges, submit/cancel orders, mutate leverage or margin, touch live-gate
state, or enable live trading. In production, the local file repository fails
closed unless a test-only override is active; durable SQLAlchemy storage must be
selected explicitly.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.adapters.db.engine import make_engine
from app.auth.security import optional_auth, require_auth
from app.auth.users import UserRecord

router = APIRouter(tags=["v2-alerts"])

SUPPORTED_ALERT_TYPES = [
    "Price movement",
    "Funding rate",
    "Open interest",
    "Liquidation activity",
    "Signal change",
    "Risk state",
]

_ALERT_LOCK = threading.Lock()
LOCAL_ALERT_REPOSITORY_KIND = "local_file"
SQL_ALERT_REPOSITORY_KIND = "sqlalchemy"


class AlertCreateRequest(BaseModel):
    alert_type: str = Field(min_length=1)
    symbol: str = "BTCUSDT"
    condition: str = Field(min_length=1)
    threshold: float | None = None
    enabled: bool = True
    note: str | None = None


class AlertUpdateRequest(BaseModel):
    alert_type: str | None = None
    symbol: str | None = None
    condition: str | None = None
    threshold: float | None = None
    enabled: bool | None = None
    muted: bool | None = None
    note: str | None = None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _repo_root() -> Path:
    return Path(os.environ.get("V2_REPO_ROOT", "/home/wali/Desktop/AI BOT REBUILD"))


def _alert_store_path() -> Path:
    configured = os.environ.get("ALPHAFORGE_ALERT_STORE", "").strip()
    if configured:
        return Path(configured)
    return _repo_root() / "v2" / "backend" / "alerts.json"


def _alert_repository_backend() -> str:
    backend = os.environ.get("ALPHAFORGE_ALERT_STORE_BACKEND", "local_file").strip().lower()
    if backend in {"sqlalchemy", "database", "db"}:
        return SQL_ALERT_REPOSITORY_KIND
    return LOCAL_ALERT_REPOSITORY_KIND


def _alert_database_url() -> str:
    configured = os.environ.get("ALPHAFORGE_ALERT_DATABASE_URL", "").strip()
    if configured:
        return configured
    raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="alert_database_url_required")


def _alert_db_auto_create_enabled() -> bool:
    return os.environ.get("ALPHAFORGE_ALERT_DB_AUTO_CREATE", "").strip().lower() in {"1", "true", "yes", "on"}


def _alert_repository_source() -> str:
    return "sqlalchemy_trader_alert_repository" if _alert_repository_backend() == SQL_ALERT_REPOSITORY_KIND else "local_trader_alert_repository"


def _alert_repository_status() -> str:
    return "sqlalchemy_repository" if _alert_repository_backend() == SQL_ALERT_REPOSITORY_KIND else "local_repository"


def _production_environment() -> bool:
    return os.environ.get("ALPHAFORGE_ENV", "").strip().lower() in {"prod", "production"}


def _local_alert_repo_allowed() -> bool:
    if not _production_environment():
        return True
    override = os.environ.get("ALPHAFORGE_ALLOW_LOCAL_ALERT_STORE_IN_PRODUCTION", "").strip().lower()
    return override in {"test", "test-only"} and bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _sql_engine():
    try:
        return make_engine(_alert_database_url())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="alert_database_url_required") from exc


def _ensure_sql_schema(engine) -> None:
    if not _alert_db_auto_create_enabled():
        return
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS alphaforge_alerts (
                    id VARCHAR(128) PRIMARY KEY,
                    trader_id VARCHAR(128) NOT NULL,
                    paper_account_id VARCHAR(128) NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at VARCHAR(64) NOT NULL
                )
                """
            )
        )


def _read_sql_records() -> list[dict[str, Any]]:
    engine = _sql_engine()
    try:
        _ensure_sql_schema(engine)
        with engine.begin() as connection:
            rows = connection.execute(text("SELECT payload_json FROM alphaforge_alerts")).fetchall()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="alert_repository_unavailable") from exc
    records: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row[0])
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _write_sql_records(rows: list[dict[str, Any]]) -> None:
    engine = _sql_engine()
    try:
        _ensure_sql_schema(engine)
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM alphaforge_alerts"))
            for row in rows:
                connection.execute(
                    text(
                        """
                        INSERT INTO alphaforge_alerts (id, trader_id, paper_account_id, payload_json, updated_at)
                        VALUES (:id, :trader_id, :paper_account_id, :payload_json, :updated_at)
                        """
                    ),
                    {
                        "id": str(row.get("id") or ""),
                        "trader_id": str(row.get("trader_id") or ""),
                        "paper_account_id": str(row.get("paper_account_id") or ""),
                        "payload_json": json.dumps(row, sort_keys=True),
                        "updated_at": str(row.get("updated_at") or _utc_now()),
                    },
                )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="alert_repository_unavailable") from exc


def _read_records() -> list[dict[str, Any]]:
    if _alert_repository_backend() == SQL_ALERT_REPOSITORY_KIND:
        return _read_sql_records()
    if not _local_alert_repo_allowed():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="production_alert_repository_required")
    path = _alert_store_path()
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = payload.get("alerts") if isinstance(payload, dict) else None
    return rows if isinstance(rows, list) else []


def _write_records(rows: list[dict[str, Any]]) -> None:
    if _alert_repository_backend() == SQL_ALERT_REPOSITORY_KIND:
        _write_sql_records(rows)
        return
    if not _local_alert_repo_allowed():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="production_alert_repository_required")
    path = _alert_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({"alerts": rows}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _trader_context(user: UserRecord | None) -> dict[str, Any]:
    if user is None:
        return {
            "scope": "public_read_only",
            "trader_id": None,
            "paper_account_id": None,
            "username": None,
            "exchange_accounts": [],
            "account_specific": False,
            "warnings": ["Sign in required for trader-specific alert preferences."],
        }
    return {
        "scope": "authenticated_trader",
        "trader_id": user.get("trader_id"),
        "paper_account_id": user.get("paper_account_id"),
        "username": user.get("username"),
        "exchange_accounts": [],
        "account_specific": bool(user.get("trader_id") and user.get("paper_account_id")),
        "warnings": [] if user.get("trader_id") and user.get("paper_account_id") else ["Trader scope is incomplete."],
    }


def _require_trader_scope(user: UserRecord) -> tuple[str, str]:
    trader_id = str(user.get("trader_id") or "").strip()
    paper_account_id = str(user.get("paper_account_id") or "").strip()
    if not trader_id or not paper_account_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="trader_alert_scope_required")
    return trader_id, paper_account_id


def _strict_alert_symbol(symbol: str | None, *, default: str | None = None) -> str | None:
    raw = (symbol or "").strip().upper()
    if not raw:
        return default
    return raw if raw.isalnum() else None


def _scoped_rows(rows: list[dict[str, Any]], trader_id: str | None, paper_account_id: str | None) -> list[dict[str, Any]]:
    if not trader_id or not paper_account_id:
        return []
    return [
        _safe_alert(row)
        for row in rows
        if row.get("trader_id") == trader_id and row.get("paper_account_id") == paper_account_id
    ]


def _safe_alert(row: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "id",
        "trader_id",
        "paper_account_id",
        "alert_type",
        "symbol",
        "condition",
        "threshold",
        "enabled",
        "muted",
        "delivery_enabled",
        "delivery_status",
        "audit_event_count",
        "created_at",
        "updated_at",
    }
    return {key: row.get(key) for key in allowed if key in row}


def _contract(
    *,
    user: UserRecord | None,
    alerts: list[dict[str, Any]] | None = None,
    source_type: str,
    source: str,
    stale: bool,
    missing_fields: list[str],
    warnings: list[str],
    action: dict[str, Any] | None = None,
) -> dict[str, Any]:
    endpoint = "/api/v2/alerts"
    trader_context = _trader_context(user)
    account_specific = trader_context["account_specific"] is True
    repository_connected = source_type == "repository" and account_specific
    data: dict[str, Any] = {
        "alerts": alerts or [],
        "supported_alert_types": SUPPORTED_ALERT_TYPES,
        "preferences": {"source": source} if repository_connected else None,
        "delivery_channels": [],
        "create_enabled": repository_connected,
        "edit_enabled": repository_connected,
        "mute_enabled": repository_connected,
        "delivery_enabled": False,
        "audit_logging_enabled": repository_connected,
        "trader_id": trader_context["trader_id"],
        "paper_account_id": trader_context["paper_account_id"],
        "account_scope": trader_context["scope"],
        "account_specific": account_specific,
        "repository_status": _alert_repository_status() if repository_connected else "unavailable",
        "delivery_status": "disabled_until_delivery_service_exists",
    }
    if action is not None:
        data["last_action"] = action
    return {
        "data": data,
        "source": source,
        "source_type": source_type,
        "endpoint": endpoint,
        "timestamp": _utc_now() if source_type == "repository" else None,
        "received_at": _utc_now(),
        "lag_ms": 0 if source_type == "repository" else None,
        "stale": stale,
        "missing_fields": missing_fields,
        "warnings": warnings + trader_context["warnings"],
        "mode": "paper" if trader_context["scope"] == "authenticated_trader" else "read_only",
        "account_scope": {
            "scope": trader_context["scope"],
            "trader_id": trader_context["trader_id"],
            "paper_account_id": trader_context["paper_account_id"],
            "data_trader_id": trader_context["trader_id"] if repository_connected else None,
            "data_paper_account_id": trader_context["paper_account_id"] if repository_connected else None,
            "authenticated": user is not None,
            "actor_scope_present": account_specific,
            "data_account_specific": repository_connected,
            "data_scope_matches_actor": repository_connected,
            "scope_verified": repository_connected,
            "live_trading_enabled": False,
            "exchange_mutation_enabled": False,
        },
        "trader_context": trader_context,
    }


def _unavailable_contract(user: UserRecord | None) -> dict[str, Any]:
    return _contract(
        user=user,
        source_type="unavailable",
        source="unavailable",
        stale=True,
        missing_fields=[
            "alert_repository",
            "alert_preferences",
            "delivery_channels",
            "notification_delivery",
            "production_alert_audit_repository",
        ],
        warnings=[
            "Alert API contract is present, but trader-scoped alert CRUD requires sign-in and repository access.",
            "No alert action was created, updated, delivered, or acknowledged.",
        ],
    )


def _invalid_alert_symbol_contract(user: UserRecord) -> dict[str, Any]:
    return _contract(
        user=user,
        source_type="unavailable",
        source="unavailable",
        stale=True,
        missing_fields=["symbol", "alert_repository"],
        warnings=[
            "Enter a valid market symbol",
            "No alert action was created, updated, delivered, or acknowledged.",
        ],
        action={"type": "rejected", "reason": "Enter a valid market symbol", "delivery_enabled": False},
    )


@router.get("/alerts")
def get_alerts(user: UserRecord | None = Depends(optional_auth)) -> dict[str, Any]:
    """Return alert contract state without mutating alert, delivery, or exchange state."""
    trader_context = _trader_context(user)
    if not user or not trader_context["account_specific"]:
        return _unavailable_contract(user)
    try:
        rows = _read_records()
    except HTTPException:
        return _unavailable_contract(user)
    alerts = _scoped_rows(rows, trader_context["trader_id"], trader_context["paper_account_id"])
    return _contract(
        user=user,
        alerts=alerts,
        source_type="repository",
        source=_alert_repository_source(),
        stale=False,
        missing_fields=["notification_delivery", "production_alert_delivery", "production_alert_audit_repository"],
        warnings=[
            "Alert CRUD is paper/read-only repository state and partial evidence only.",
            "Notification delivery remains disabled until a delivery service and production audit repository exist.",
            "No exchange state is read or mutated by alert actions.",
        ],
    )


@router.post("/alerts", status_code=status.HTTP_201_CREATED)
def create_alert(
    request: AlertCreateRequest,
    response: Response,
    user: UserRecord = Depends(require_auth),
) -> dict[str, Any]:
    trader_id, paper_account_id = _require_trader_scope(user)
    alert_type = request.alert_type.strip()
    if alert_type not in SUPPORTED_ALERT_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported_alert_type")
    symbol = _strict_alert_symbol(request.symbol, default="BTCUSDT")
    if symbol is None:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return _invalid_alert_symbol_contract(user)
    now = _utc_now()
    row = {
        "id": f"alert-{uuid4().hex}",
        "trader_id": trader_id,
        "paper_account_id": paper_account_id,
        "alert_type": alert_type,
        "symbol": symbol,
        "condition": request.condition.strip(),
        "threshold": request.threshold,
        "enabled": bool(request.enabled),
        "muted": False,
        "delivery_enabled": False,
        "delivery_status": "disabled_until_delivery_service_exists",
        "note": request.note,
        "audit_event_count": 1,
        "audit_events": [{"event_type": "alert_create", "recorded_at": now}],
        "created_at": now,
        "updated_at": now,
    }
    with _ALERT_LOCK:
        rows = _read_records()
        rows.append(row)
        _write_records(rows)
    return _contract(
        user=user,
        alerts=_scoped_rows(rows, trader_id, paper_account_id),
        source_type="repository",
        source=_alert_repository_source(),
        stale=False,
        missing_fields=["notification_delivery", "production_alert_delivery", "production_alert_audit_repository"],
        warnings=["Alert saved for paper/read-only use; delivery remains disabled."],
        action={"type": "created", "alert_id": row["id"], "delivery_enabled": False},
    )


@router.put("/alerts/{alert_id}")
def update_alert(
    alert_id: str,
    request: AlertUpdateRequest,
    response: Response,
    user: UserRecord = Depends(require_auth),
) -> dict[str, Any]:
    trader_id, paper_account_id = _require_trader_scope(user)
    updates = request.model_dump(exclude_unset=True)
    now = _utc_now()
    with _ALERT_LOCK:
        rows = _read_records()
        for index, row in enumerate(rows):
            if row.get("id") != alert_id or row.get("trader_id") != trader_id or row.get("paper_account_id") != paper_account_id:
                continue
            next_row = dict(row)
            if "alert_type" in updates:
                alert_type = str(updates["alert_type"] or "").strip()
                if alert_type not in SUPPORTED_ALERT_TYPES:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported_alert_type")
                next_row["alert_type"] = alert_type
            if "symbol" in updates and updates["symbol"] is not None:
                symbol = _strict_alert_symbol(str(updates["symbol"]))
                if symbol is None:
                    response.status_code = status.HTTP_400_BAD_REQUEST
                    return _invalid_alert_symbol_contract(user)
                next_row["symbol"] = symbol
            if "condition" in updates and updates["condition"] is not None:
                next_row["condition"] = str(updates["condition"]).strip()
            for key in ("threshold", "enabled", "muted", "note"):
                if key in updates:
                    next_row[key] = updates[key]
            next_row["delivery_enabled"] = False
            next_row["delivery_status"] = "disabled_until_delivery_service_exists"
            audit_events = list(next_row.get("audit_events") or [])
            audit_events.append({"event_type": "alert_update", "recorded_at": now})
            next_row["audit_events"] = audit_events
            next_row["audit_event_count"] = len(audit_events)
            next_row["updated_at"] = now
            rows[index] = next_row
            _write_records(rows)
            return _contract(
                user=user,
                alerts=_scoped_rows(rows, trader_id, paper_account_id),
                source_type="repository",
                source=_alert_repository_source(),
                stale=False,
                missing_fields=["notification_delivery", "production_alert_delivery", "production_alert_audit_repository"],
                warnings=["Alert updated for paper/read-only use; delivery remains disabled."],
                action={"type": "updated", "alert_id": alert_id, "delivery_enabled": False},
            )
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="alert_not_found")


@router.delete("/alerts/{alert_id}")
def delete_alert(alert_id: str, user: UserRecord = Depends(require_auth)) -> dict[str, Any]:
    trader_id, paper_account_id = _require_trader_scope(user)
    with _ALERT_LOCK:
        rows = _read_records()
        next_rows = [
            row
            for row in rows
            if not (row.get("id") == alert_id and row.get("trader_id") == trader_id and row.get("paper_account_id") == paper_account_id)
        ]
        if len(next_rows) == len(rows):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="alert_not_found")
        _write_records(next_rows)
    return _contract(
        user=user,
        alerts=_scoped_rows(next_rows, trader_id, paper_account_id),
        source_type="repository",
        source=_alert_repository_source(),
        stale=False,
        missing_fields=["notification_delivery", "production_alert_delivery", "production_alert_audit_repository"],
        warnings=["Alert deleted for paper/read-only use; delivery remains disabled."],
        action={"type": "deleted", "alert_id": alert_id, "delivery_enabled": False},
    )
