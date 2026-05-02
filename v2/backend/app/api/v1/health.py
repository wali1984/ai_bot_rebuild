"""`/_meta/` endpoints — health, build info, readiness, agent supervisor (§7).

Originally a scaffold-only OPTIONS shim. Milestone B (015F) materializes the
agent-supervisor reader endpoints used by the V2 dashboard:

- GET /_meta/agent-health    — supervisor heartbeat + agent readiness
- GET /_meta/queue-status    — queue counts, gate, and stale-state alert lists
- GET /_meta/build-status    — recent runs/<task_id>/summary.json entries
- GET /_meta/audit-chain     — events.jsonl tail + chain-integrity verdict

All four endpoints are READ-ONLY against
`claude_worklog/agent_supervisor/**`. The reader service uses Python's
`open(..., "r")` exclusively and the integration suite proves the supervisor
tree's size+mtime is byte-stable across requests.

Live trading is BLOCKED. These endpoints sit under `/_meta` so the
live-block guard never matches them.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.services.agent_supervisor_reader import (
    read_agent_health,
    read_audit_chain,
    read_build_status,
    read_queue_status,
)

router = APIRouter(prefix="/_meta", tags=["_meta"])

ROUTE_METADATA: dict[str, Any] = {
    "group": "_meta",
    "prefix": "/_meta",
    "endpoints": (
        "/health",
        "/build",
        "/readiness",
        "/agent-health",
        "/queue-status",
        "/build-status",
        "/audit-chain",
    ),
    "rbac": "public",
    "milestone_d_status": "skeleton",
    "milestone_b_015f_status": "agent_supervisor_reader_wired",
}


@router.options("/", include_in_schema=False)
async def _route_metadata() -> dict[str, Any]:
    return ROUTE_METADATA


@router.get("/agent-health")
async def get_agent_health() -> dict[str, Any]:
    return read_agent_health()


@router.get("/queue-status")
async def get_queue_status() -> dict[str, Any]:
    return read_queue_status()


@router.get("/build-status")
async def get_build_status(
    limit: int = Query(default=25, ge=1, le=200),
) -> dict[str, Any]:
    return read_build_status(limit=limit)


@router.get("/audit-chain")
async def get_audit_chain(
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    return read_audit_chain(limit=limit)
