from __future__ import annotations

from fastapi import APIRouter

try:  # Uvicorn service runs with PYTHONPATH=v2/backend.
    from app.services.operator_truth.realtime_runtime_truth import publish_realtime_runtime_truth
except ImportError:  # CLI/tests may import from the repo root package.
    from v2.backend.app.services.operator_truth.realtime_runtime_truth import publish_realtime_runtime_truth

router = APIRouter(prefix="/operator-runtime", tags=["operator-runtime"])


@router.get("/truth")
async def get_operator_runtime_truth() -> dict:
    payloads = publish_realtime_runtime_truth()
    return payloads["operator_runtime_truth.json"]


@router.get("/stream")
async def get_operator_runtime_stream_status() -> dict:
    payloads = publish_realtime_runtime_truth()
    return {
        "status": "SSE_NOT_ENABLED_STATIC_POLLING_AVAILABLE",
        "poll_endpoint": "/api/v1/operator-runtime/truth",
        "static_payload": "/operator_runtime/v2_runtime_truth/latest/runtime_pages_payload.json",
        "generated_est": payloads["operator_runtime_truth.json"].get("generated_est"),
    }
