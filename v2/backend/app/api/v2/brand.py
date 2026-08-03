"""Read-only NERVYX ONE presentation metadata.

This endpoint is additive and does not rename internal services, payload keys,
Redis topics, database columns, or route paths.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["v2-brand"])


@router.get("/brand")
async def get_brand_metadata() -> dict[str, object]:
    return {
        "product_name": "NERVYX ONE",
        "descriptor": "Adaptive Market Intelligence",
        "tagline": "Sense. Decide. Adapt.",
        "secondary_line": "One system. Every market state.",
        "active_theme_names": ["Midnight Neural", "Polar Signal", "Ops Terminal"],
        "theme_policy": {
            "default_public": "Midnight Neural",
            "default_trader": "Midnight Neural",
            "selectable_public_trader": ["Midnight Neural", "Polar Signal"],
            "admin_only": "Ops Terminal",
            "role_source": "backend_authoritative",
        },
        "module_display_names": {
            "sense": "NERVYX SENSE",
            "core": "NERVYX CORE",
            "shift": "NERVYX SHIFT",
            "guard": "NERVYX GUARD",
            "replay": "NERVYX REPLAY",
            "execute": "NERVYX EXECUTE",
            "observe": "NERVYX OBSERVE",
        },
        "module_route_mapping": {
            "markets": "sense",
            "derivatives": "sense",
            "signals": "sense",
            "ai_predictions": "core",
            "trainer": "core",
            "orchestrator": "shift",
            "risk": "guard",
            "live_readiness": "guard",
            "backtests": "replay",
            "audit": "replay",
            "trade": "execute",
            "portfolio": "execute",
            "orders": "execute",
            "executions": "execute",
            "admin_monitoring": "observe",
            "system_health": "observe",
        },
        "compatibility_policy": {
            "renames_internal_services": False,
            "renames_payload_keys": False,
            "renames_api_paths": False,
            "enables_live_trading": False,
            "presentation_aliases_only": True,
        },
        "data_contract_policy": {
            "preserve_existing_fields": True,
            "preserve_existing_endpoints": True,
            "sensitive_fields_public": False,
            "live_trading_default": "blocked_human_only",
        },
        "asset_version": "36bf9013c0a1",
        "token_version": "36bf9013c0a1",
        "live_trading_enabled": False,
        "places_real_order": False,
    }
