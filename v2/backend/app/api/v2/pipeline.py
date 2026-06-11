"""Safe V2 trainer/replay/backtest/full-pipeline control surface.

The route records operator run requests for workers to consume. It never
executes training inline, restarts services, imports legacy trainer code, or
calls an exchange.
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.v2._common import get_redis, require_min_role
from app.services.pipeline_control.service import (
    ALLOWED_RUN_TYPES,
    build_pipeline_status,
    normalize_control_request,
    record_pipeline_control_request,
)

router = APIRouter(prefix="/pipeline", tags=["v2-pipeline-control"])


class PipelineRunRequest(BaseModel):
    run_type: Literal["trainer_cycle", "replay", "backtest", "full_pipeline"]
    symbols: list[str] | None = Field(default=None)
    timeframes: list[str] | None = Field(default=None)
    dry_run: bool = True
    max_rows: int = Field(default=8192, ge=1, le=250_000)
    requested_by: str = Field(default="website", max_length=64)
    reason: str = Field(default="operator_requested_from_website", max_length=256)


def _csv(value: str | None) -> list[str] | None:
    if value is None or not value.strip():
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


@router.get("/status")
async def get_pipeline_status(
    symbols: str | None = Query(default=None),
    timeframes: str | None = Query(default=None),
) -> dict[str, Any]:
    return build_pipeline_status(
        get_redis(),
        symbols=_csv(symbols),
        timeframes=_csv(timeframes),
    )


@router.post("/run")
async def request_pipeline_run(
    request: PipelineRunRequest,
    _role: str = Depends(require_min_role("operator")),
) -> dict[str, Any]:
    try:
        normalized = normalize_control_request(
            run_type=request.run_type,
            symbols=request.symbols,
            timeframes=request.timeframes,
            dry_run=request.dry_run,
            max_rows=request.max_rows,
            requested_by=request.requested_by,
            reason=request.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return record_pipeline_control_request(get_redis(), request=normalized)


@router.options("/", include_in_schema=False)
async def _route_metadata() -> dict[str, Any]:
    return {
        "group": "pipeline",
        "prefix": "/pipeline",
        "endpoints": ("/status", "/run"),
        "rbac": "operator_for_run",
        "allowed_run_types": list(ALLOWED_RUN_TYPES),
        "live_gate": "reported_by_/api/v2/pipeline/status",
        "live_symbols": "reported_by_/api/v2/pipeline/status",
        "exchange_action_taken": False,
    }
