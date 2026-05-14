"""`/config-admin/` endpoints for V2 config/admin records."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from v2.backend.app.cli.v2_config_admin_manager import build_status


router = APIRouter(prefix="/config-admin", tags=["config-admin"])


@router.get("/settings")
async def list_settings() -> Dict[str, Any]:
    status = build_status()
    return {
        "live_gate": status["live_gate"],
        "settings": status["settings"],
        "settings_by_risk_class": status["settings_by_risk_class"],
        "dangerous_settings_pending_approval": status["dangerous_settings_pending_approval"],
        "secrets_written_to_payload": status["secrets_written_to_payload"],
    }


@router.get("/status")
async def config_admin_status() -> Dict[str, Any]:
    return build_status()
