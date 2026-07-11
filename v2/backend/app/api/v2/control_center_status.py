"""Read-only control-center status aliases.

These endpoints exist so web, iOS, and authenticated crawlers can depend on
canonical JSON contracts instead of accidentally accepting SPA HTML fallbacks.
They never place orders, submit test orders, or mutate exchange settings.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from app.api.v2._common import get_redis
from app.services.realtime.operator_snapshot import build_ui_snapshot

router = APIRouter(tags=["v2-control-center-status"])

DISPLAY_TZ = ZoneInfo("America/New_York")
PREVIEW_LIMIT = 25


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _display_time_et() -> str:
    return datetime.now(DISPLAY_TZ).isoformat(timespec="seconds")


def _json_object(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(str(raw))
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_json(client: Any, key: str) -> dict[str, Any]:
    if client is None:
        return {}
    try:
        return _json_object(client.get(key))
    except Exception:
        return {}


def _first(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _a_plus_blocker_summary(
    payload: Mapping[str, Any],
    rows: list[Any],
    *,
    a_plus_count: int,
) -> tuple[str | None, list[str]]:
    """Return exact A+ blockers without synthesizing a live-ready-sounding label."""
    if a_plus_count > 0:
        return None, []

    reason_counts: dict[str, int] = {}
    matrix = payload.get("rejected_reason_matrix")
    if isinstance(matrix, Mapping):
        for reason, count in matrix.items():
            if not reason:
                continue
            try:
                parsed_count = int(count)
            except (TypeError, ValueError):
                parsed_count = 1
            reason_counts[str(reason)] = max(parsed_count, 1)

    for row in rows:
        if not isinstance(row, Mapping):
            continue
        failed_checks = row.get("failed_checks")
        if isinstance(failed_checks, list):
            for reason in failed_checks:
                if reason:
                    key = str(reason)
                    reason_counts[key] = reason_counts.get(key, 0) + 1

    top_blockers = [
        reason
        for reason, _count in sorted(
            reason_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ][:8]
    if top_blockers:
        return top_blockers[0], top_blockers

    evaluated = payload.get("evaluated_candidates")
    try:
        evaluated_count = int(evaluated)
    except (TypeError, ValueError):
        evaluated_count = len(rows)
    if evaluated_count <= 0 and not rows:
        return "NO_EVALUATED_CANDIDATES_IN_A_PLUS_GATE_STATUS", []
    return "A_PLUS_GATE_REJECTION_REASON_MISSING_FROM_RUNTIME_PAYLOAD", []


def _parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _payload_timestamp(payload: Mapping[str, Any]) -> str | None:
    value = _first(
        payload.get("generated_at_utc"),
        payload.get("generated_utc"),
        payload.get("generated_at"),
        payload.get("available_at"),
        payload.get("updated_at"),
    )
    return str(value) if value is not None else None


def _age_seconds(payload: Mapping[str, Any], fallback: Any = None) -> float | None:
    if isinstance(fallback, (int, float)):
        return max(0.0, float(fallback))
    parsed = _parse_utc(_payload_timestamp(payload))
    if parsed is None:
        return None
    return max(0.0, (datetime.now(UTC) - parsed).total_seconds())


def _freshness(age_seconds: float | None, *, has_payload: bool) -> str:
    if not has_payload:
        return "missing"
    if age_seconds is None:
        return "unknown"
    if age_seconds <= 300:
        return "fresh"
    if age_seconds <= 1800:
        return "degraded"
    return "stale"


def _data_quality(*, has_payload: bool, freshness_status: str, source_quality: Any = None) -> str:
    if not has_payload:
        return "missing"
    quality = str(source_quality or "").lower()
    if quality in {"fresh", "valid"} and freshness_status == "fresh":
        return "fresh"
    if freshness_status in {"stale", "degraded"}:
        return freshness_status
    if freshness_status == "fresh":
        return "fresh"
    if quality:
        return quality
    return "partial"


def _contract(
    *,
    schema_version: str,
    canonical_owner: str,
    source: str,
    data: dict[str, Any],
    source_quality: Any = None,
    staleness_seconds: float | None = None,
) -> dict[str, Any]:
    has_payload = bool(data)
    age = _age_seconds(data, staleness_seconds)
    freshness_status = _freshness(age, has_payload=has_payload)
    return {
        "schema_version": schema_version,
        "generated_at_utc": _utc_now(),
        "generated_at_et": _display_time_et(),
        "source": source,
        "staleness_seconds": age,
        "freshness_status": freshness_status,
        "canonical_owner": canonical_owner,
        "live_gate": "blocked_human_only",
        "places_real_order": False,
        "routes_to_live": False,
        "data_quality_status": _data_quality(
            has_payload=has_payload,
            freshness_status=freshness_status,
            source_quality=source_quality,
        ),
        "data": data,
    }


@router.get("/providers/status")
async def get_provider_status() -> dict[str, Any]:
    client = get_redis()
    snapshot = build_ui_snapshot(client, "providers", use_materialized=False)
    payload = snapshot.get("payload") if isinstance(snapshot.get("payload"), dict) else {}
    data = dict(payload)
    data["provider_count"] = len(data.get("providers") or [])
    data["consumer_surface"] = "web_ios_control_center"
    data["source_snapshot_schema_version"] = snapshot.get("schema_version")
    return _contract(
        schema_version="control_center_provider_status_v1",
        canonical_owner="/api/v2/providers/status",
        source=str(snapshot.get("source") or "compact_live_fallback"),
        data=data,
        source_quality=snapshot.get("data_quality"),
        staleness_seconds=snapshot.get("staleness_seconds"),
    )


@router.get("/live-canary/status")
async def get_live_canary_status() -> dict[str, Any]:
    client = get_redis()
    payload = _read_json(client, "v2:live_canary:status")
    data = {
        "generated_utc": payload.get("generated_utc"),
        "status_payload": payload,
        "selected_a_plus_candidate": _first(payload.get("selected_a_plus_candidate"), payload.get("active_candidate")),
        "why_none": _first(payload.get("why_none"), payload.get("live_blocker"), payload.get("go_no_go")),
        "dry_run": payload.get("dry_run", True),
        "operator_approval_required": True,
        "order_builder_dry_run": {
            "available": bool(payload),
            "post_only_maker_first": payload.get("post_only_maker_first"),
            "taker_fallback_reason": payload.get("taker_fallback_reason"),
            "reduce_close_path": payload.get("reduce_close_path"),
        },
        "no_mutation_flags": {
            "real_order_attempted": bool(payload.get("real_order_attempted")),
            "real_order_submitted": bool(payload.get("real_order_submitted")),
            "test_order_submitted": bool(payload.get("test_order_submitted")),
            "leverage_changed": bool(payload.get("leverage_changed")),
            "margin_mode_changed": bool(payload.get("margin_mode_changed")),
            "places_real_order": False,
            "routes_to_live": False,
        },
    }
    return _contract(
        schema_version="control_center_live_canary_status_v1",
        canonical_owner="/api/v2/live-canary/status",
        source="redis:v2:live_canary:status",
        data=data,
    )


@router.get("/a-plus/inventory")
async def get_a_plus_inventory() -> dict[str, Any]:
    client = get_redis()
    payload = _read_json(client, "v2:paper:a_plus_gate:status")
    rows = payload.get("candidate_matrix") if isinstance(payload.get("candidate_matrix"), list) else []
    a_plus_rows = [row for row in rows if isinstance(row, dict) and row.get("a_plus") is True]
    live_ready_rows = [
        row for row in rows if isinstance(row, dict) and row.get("live_ready") is True
    ]
    exact_no_a_plus_reason, top_a_plus_blockers = _a_plus_blocker_summary(
        payload,
        rows,
        a_plus_count=len(a_plus_rows),
    )
    data = {
        "schema_version": payload.get("schema_version"),
        "generated_utc": payload.get("generated_utc"),
        "paper_session_id": payload.get("paper_session_id"),
        "evaluated_candidates": payload.get("evaluated_candidates", len(rows)),
        "a_plus_candidates": payload.get("a_plus_candidates", len(a_plus_rows)),
        "live_ready_rows": len(live_ready_rows),
        "exact_no_a_plus_reason": exact_no_a_plus_reason,
        "top_a_plus_blockers": top_a_plus_blockers,
        "counts_as_final_a_plus": False,
        "b_grade_counts_as_final_a_plus": False,
        "probation_counts_as_final_a_plus": False,
        "rejected_reason_matrix": payload.get("rejected_reason_matrix"),
        "candidate_matrix_preview": rows[:PREVIEW_LIMIT],
        "a_plus_preview": a_plus_rows[:PREVIEW_LIMIT],
        "payload_compacted": len(rows) > PREVIEW_LIMIT,
        "full_candidate_count": len(rows),
    }
    return _contract(
        schema_version="control_center_a_plus_inventory_v1",
        canonical_owner="/api/v2/a-plus/inventory",
        source="redis:v2:paper:a_plus_gate:status",
        data=data,
    )
