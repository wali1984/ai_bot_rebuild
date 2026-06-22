"""Append-only local paper audit ledger.

This module is paper-only evidence infrastructure. It does not submit, cancel,
or mutate exchange orders, does not read exchange state, and does not enable
live trading. It writes hash-chained paper audit event rows to a local JSONL
file so account-embedded audit rows are not the only local evidence surface.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

from app.domain.governance.audit_chain import verify_local_paper_audit_chain


_LEDGER_LOCK = threading.Lock()
LOCAL_PAPER_AUDIT_LEDGER_KIND = "append_only_local_jsonl"


def _repo_root() -> Path:
    return Path(os.environ.get("V2_REPO_ROOT", "/home/wali/Desktop/AI BOT REBUILD"))


def _ledger_path() -> Path:
    configured = os.environ.get("ALPHAFORGE_PAPER_AUDIT_LEDGER_STORE", "").strip()
    if configured:
        return Path(configured)
    return _repo_root() / "v2" / "backend" / "paper_audit_ledger.jsonl"


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _paper_audit_retention_days() -> int | None:
    raw = os.environ.get("ALPHAFORGE_PAPER_AUDIT_RETENTION_DAYS", "").strip()
    if not raw:
        return None
    try:
        days = int(raw)
    except ValueError:
        return None
    if days <= 0:
        return None
    return days


def _production_environment() -> bool:
    return os.environ.get("ALPHAFORGE_ENV", "").strip().lower() in {"prod", "production"}


def _durable_paper_audit_policy_artifact_path() -> Path | None:
    configured = os.environ.get("ALPHAFORGE_DURABLE_PAPER_AUDIT_POLICY_ARTIFACT", "").strip()
    return Path(configured) if configured else None


def _durable_paper_audit_policy_evidence() -> dict[str, Any]:
    artifact_path = _durable_paper_audit_policy_artifact_path()
    if artifact_path is None:
        return {
            "configured": False,
            "valid": False,
            "status": "pending",
            "warnings": ["Durable paper audit policy artifact is not configured"],
        }
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {
            "configured": True,
            "valid": False,
            "status": "invalid",
            "warnings": [f"Durable paper audit policy artifact could not be read: {exc}"],
        }
    if not isinstance(payload, dict):
        return {
            "configured": True,
            "valid": False,
            "status": "invalid",
            "warnings": ["Durable paper audit policy artifact must be a JSON object"],
        }
    status_value = str(
        payload.get("durable_paper_audit_policy_status") or payload.get("status") or ""
    ).strip().lower()
    production_durable_store = payload.get("production_durable_store") is True
    retention_enforced = payload.get("retention_enforced") is True
    writer_hardened = (
        payload.get("production_writer_hardened") is True
        or payload.get("writer_hardening_verified") is True
    )
    audit_verified = (
        payload.get("audit_verification_passed") is True
        or payload.get("audit_chain_verification_passed") is True
    )
    live_disabled = payload.get("live_transport_enabled") is False
    exchange_disabled = payload.get("exchange_mutation_enabled") is False
    valid = (
        status_value in {"pass", "passed", "ok", "verified"}
        and production_durable_store
        and retention_enforced
        and writer_hardened
        and audit_verified
        and live_disabled
        and exchange_disabled
    )
    warnings = list(payload.get("warnings") or []) if isinstance(payload.get("warnings"), list) else []
    if not valid:
        warnings.append(
            "Durable paper audit policy artifact must prove durable store, enforced retention, writer hardening, audit verification, and disabled live/exchange mutation"
        )
    return {
        "configured": True,
        "valid": valid,
        "status": "verified" if valid else "invalid",
        "production_durable_store": production_durable_store,
        "retention_enforced": retention_enforced,
        "production_writer_hardened": writer_hardened,
        "audit_verification_passed": audit_verified,
        "warnings": [str(warning) for warning in warnings],
    }


def append_local_paper_audit_event(event: dict[str, Any]) -> dict[str, Any]:
    """Append one paper audit event to the local ledger.

    A failure to persist the local audit row raises. Callers can then avoid
    recording a paper order state mutation without its matching audit evidence.
    """

    if not event.get("trader_id") or not event.get("paper_account_id"):
        raise ValueError("paper audit event requires trader_id and paper_account_id")
    if event.get("exchange_mutation_enabled") is not False or event.get("live_transport_enabled") is not False:
        raise ValueError("paper audit ledger rejects events without disabled live/exchange mutation flags")
    if _production_environment():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="production_paper_audit_ledger_required",
        )
    path = _ledger_path()
    retention_days = _paper_audit_retention_days()
    durable_policy = _durable_paper_audit_policy_evidence()
    record = {
        **event,
        "ledger_kind": LOCAL_PAPER_AUDIT_LEDGER_KIND,
        "ledger_recorded_at": _now(),
        "ledger_append_only": True,
        "ledger_path_configured": bool(os.environ.get("ALPHAFORGE_PAPER_AUDIT_LEDGER_STORE", "").strip()),
        "retention_policy_configured": retention_days is not None,
        "retention_days": retention_days,
        "retention_enforced": False,
        "durable_paper_audit_policy_status": "partial_local_retention_metadata"
        if retention_days is not None
        else "missing",
        "durable_paper_audit_policy_artifact_configured": bool(durable_policy["configured"]),
        "durable_paper_audit_policy_artifact_valid": bool(durable_policy["valid"]),
        "durable_paper_audit_policy_artifact_status": str(durable_policy["status"]),
        "production_durable_store": False,
    }
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    with _LEDGER_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(encoded + "\n")
    return record


def read_local_paper_audit_events(
    *,
    trader_id: str,
    paper_account_id: str,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    if not trader_id or not paper_account_id:
        return []
    path = _ledger_path()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    events: list[dict[str, Any]] = []
    for line in reversed(lines):
        if len(events) >= limit:
            break
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("trader_id") != trader_id or event.get("paper_account_id") != paper_account_id:
            continue
        events.append(event)
    return events


def local_paper_audit_ledger_metadata(*, event_count: int, events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    retention_days = _paper_audit_retention_days()
    durable_policy = _durable_paper_audit_policy_evidence()
    missing_fields = ["durable_paper_audit_policy", "durable_paper_audit_policy_current_validation"]
    if not durable_policy["valid"]:
        missing_fields.append("durable_paper_audit_policy_artifact")
    warnings = ["Local paper audit ledger is partial evidence only; production durable audit storage is missing"]
    if retention_days is None:
        missing_fields.append("paper_audit_retention_days")
        warnings.append("Paper audit retention policy is not configured")
    else:
        warnings.append("Paper audit retention metadata is configured but production enforcement remains pending")
    warnings.extend(str(warning) for warning in durable_policy["warnings"])
    durable_status = (
        "artifact_present_pending_current_validation"
        if durable_policy["valid"]
        else "partial_local_retention_metadata"
        if retention_days is not None
        else "missing"
    )
    return {
        "ledger_path": str(_ledger_path()),
        "ledger_kind": LOCAL_PAPER_AUDIT_LEDGER_KIND,
        "append_only_local_file": True,
        "event_count": event_count,
        "chain_integrity": verify_local_paper_audit_chain(events or [], expected_event_count=event_count),
        "path_configured": bool(os.environ.get("ALPHAFORGE_PAPER_AUDIT_LEDGER_STORE", "").strip()),
        "retention_policy_configured": retention_days is not None,
        "retention_days": retention_days,
        "retention_enforced": False,
        "durable_paper_audit_policy_status": durable_status,
        "durable_paper_audit_policy_artifact_configured": bool(durable_policy["configured"]),
        "durable_paper_audit_policy_artifact_valid": bool(durable_policy["valid"]),
        "durable_paper_audit_policy_artifact_status": str(durable_policy["status"]),
        "durable_paper_audit_policy_artifact_production_durable_store": bool(
            durable_policy.get("production_durable_store")
        ),
        "durable_paper_audit_policy_artifact_retention_enforced": bool(
            durable_policy.get("retention_enforced")
        ),
        "durable_paper_audit_policy_artifact_writer_hardened": bool(
            durable_policy.get("production_writer_hardened")
        ),
        "durable_paper_audit_policy_artifact_audit_verified": bool(
            durable_policy.get("audit_verification_passed")
        ),
        "production_durable_store": False,
        "live_mutation_prohibited": True,
        "missing_fields": missing_fields,
        "warnings": warnings,
    }
