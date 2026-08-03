from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from typing import Any
from pathlib import Path

from fastapi import HTTPException, status


_STORE_ENV = "ALPHAFORGE_ADMIN_AUDIT_STORE"
_LOG_STORE_ENV = "ALPHAFORGE_ADMIN_AUDIT_LOG_STORE"


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _production_environment() -> bool:
    return os.environ.get("ALPHAFORGE_ENV", "").strip().lower() in {"prod", "production"}


def _backend() -> str:
    raw = os.environ.get("ALPHAFORGE_ADMIN_AUDIT_STORE_BACKEND", "local_file").strip().lower()
    return "sqlalchemy" if raw in {"sqlalchemy", "database", "db"} else "local_file"


def _local_file_production_override() -> bool:
    override = os.environ.get("ALPHAFORGE_ALLOW_LOCAL_ADMIN_AUDIT_IN_PRODUCTION", "").strip().lower()
    return override in {"test", "test-only"} and bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _retention_days() -> int | None:
    raw = os.environ.get("ALPHAFORGE_ADMIN_AUDIT_RETENTION_DAYS", "").strip()
    if not raw:
        return None
    try:
        days = int(raw)
    except ValueError:
        return None
    return days if days > 0 else None


def _audit_path() -> str | None:
    p = os.environ.get(_LOG_STORE_ENV, "").strip() or os.environ.get(_STORE_ENV, "").strip()
    return p or None


def _database_path() -> Path | None:
    url = os.environ.get("ALPHAFORGE_ADMIN_AUDIT_DATABASE_URL", "").strip()
    if not url:
        return None
    if url.startswith("sqlite:///"):
        return Path(url.removeprefix("sqlite:///"))
    return None


def _base_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "audit_id": str(uuid.uuid4()),
        "ts_ms": int(time.time() * 1000),
        **event,
        "contains_secret_values": False,
        "live_mutation_prohibited": True,
        "live_trading_enabled": False,
        "exchange_mutation_enabled": False,
    }


def _require_production_policy() -> None:
    if not _production_environment():
        return
    if _backend() == "local_file" and not _local_file_production_override():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="production_admin_audit_repository_required",
        )
    if _retention_days() is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="production_admin_audit_retention_policy_required",
        )


def _append_local_event(event: dict[str, Any]) -> dict[str, Any]:
    record = {
        **event,
        "audit_persisted": True,
        "ledger_kind": "append_only_local_admin_jsonl",
        "production_durable_store": False,
    }
    path = _audit_path()
    if not path:
        path = str(Path(os.environ.get("V2_REPO_ROOT", "/home/wali/Desktop/AI BOT REBUILD")) / "admin_audit.jsonl")
    try:
        audit_path = Path(path)
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    except OSError as exc:
        if _production_environment():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="admin_audit_log_unwritable_in_production",
            ) from exc
        return {
            **record,
            "audit_persisted": False,
        }
    return record


def _append_sql_event(event: dict[str, Any]) -> dict[str, Any]:
    retention = _retention_days()
    record = {
        **event,
        "audit_persisted": True,
        "ledger_kind": "sqlalchemy_admin_audit",
        "production_durable_store": True,
        "retention_policy_configured": retention is not None,
        "retention_days": retention,
        "retention_enforced": False,
    }
    db_path = _database_path()
    if db_path is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="admin_audit_database_url_required",
        )
    if _truthy(os.environ.get("ALPHAFORGE_ADMIN_AUDIT_DB_AUTO_CREATE")):
        db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sqlite3.connect(db_path) as conn:
            if _truthy(os.environ.get("ALPHAFORGE_ADMIN_AUDIT_DB_AUTO_CREATE")):
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS alphaforge_admin_audit_events (
                        audit_id TEXT PRIMARY KEY,
                        event_type TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        ts_ms INTEGER NOT NULL
                    )
                    """
                )
            conn.execute(
                """
                INSERT INTO alphaforge_admin_audit_events (audit_id, event_type, payload, ts_ms)
                VALUES (?, ?, ?, ?)
                """,
                (
                    event["audit_id"],
                    str(event.get("event_type") or "admin_audit_event"),
                    json.dumps(record, sort_keys=True, separators=(",", ":")),
                    int(event["ts_ms"]),
                ),
            )
            conn.commit()
    except sqlite3.Error as exc:
        if _production_environment():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="admin_audit_database_unwritable_in_production",
            ) from exc
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="admin_audit_database_unwritable") from exc
    return record


def append_admin_audit_event(event: dict[str, Any]) -> dict[str, Any]:
    _require_production_policy()
    enriched = _base_event(event)
    if _backend() == "sqlalchemy":
        return _append_sql_event(enriched)
    return _append_local_event(enriched)


def admin_audit_status() -> dict[str, Any]:
    backend = _backend()
    production = _production_environment()
    retention = _retention_days()
    path = _audit_path()
    configured = bool(path) or backend == "sqlalchemy"
    count = 0
    if backend == "local_file" and path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                count = sum(1 for line in fh if line.strip())
        except OSError:
            pass
    if backend == "sqlalchemy":
        db_path = _database_path()
        if db_path and db_path.exists():
            try:
                with sqlite3.connect(db_path) as conn:
                    row = conn.execute("SELECT COUNT(*) FROM alphaforge_admin_audit_events").fetchone()
                    count = int(row[0]) if row else 0
            except sqlite3.Error:
                count = 0
    missing_fields = []
    if retention is None:
        missing_fields.append("admin_audit_retention_days")
    if production and backend == "local_file" and not _local_file_production_override():
        missing_fields.append("admin_audit_database_backend")
    return {
        "backend": backend,
        "configured": configured,
        "path": path,
        "database_url_configured": _database_path() is not None,
        "event_count": count,
        "status": "active" if configured else "unconfigured",
        "production_environment": production,
        "append_only_local_file": backend == "local_file",
        "production_durable_store": backend == "sqlalchemy",
        "production_local_file_blocked": production and backend == "local_file" and not _local_file_production_override(),
        "retention_policy_configured": retention is not None,
        "retention_days": retention,
        "retention_policy_status": "configured_pending_enforcement" if retention is not None else "missing",
        "retention_enforced": False,
        "production_retention_policy_required": production and retention is None,
        "missing_fields": missing_fields,
        "contains_secret_values": False,
        "live_mutation_prohibited": True,
        "live_trading_enabled": False,
        "exchange_mutation_enabled": False,
    }
