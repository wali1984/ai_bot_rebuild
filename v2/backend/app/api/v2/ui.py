"""Enterprise UI materialized snapshot routes.

Routes are read-only and return compact contracts for public web/iOS
surfaces. Heavy legacy endpoints remain available as fallbacks, but these
routes do not scan Redis keyspace or assemble dozens of files per request.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.v2._common import get_redis
from app.services.realtime import build_ui_snapshot
from app.services.realtime.resource_registry import resource_contracts

router = APIRouter(prefix="/ui", tags=["enterprise-ui"])


@router.get("/resources")
async def get_ui_resources() -> dict:
    return {
        "schema_version": "enterprise_ui_resources_v1",
        "resources": resource_contracts(),
        "routes_to_live": False,
        "places_real_order": False,
    }


@router.get("/{resource}")
async def get_ui_snapshot(resource: str) -> dict:
    try:
        return build_ui_snapshot(get_redis(), resource)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"unknown_resource:{exc.args[0]}") from exc
