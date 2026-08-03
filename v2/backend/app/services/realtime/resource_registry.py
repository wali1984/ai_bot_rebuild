"""Resource registry for the enterprise UI realtime contract."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResourceContract:
    name: str
    redis_key: str
    endpoint: str
    cadence_seconds: int
    description: str


RESOURCE_CONTRACTS: tuple[ResourceContract, ...] = (
    ResourceContract("dashboard", "v2:ui:snapshot:dashboard", "/api/v2/ui/dashboard", 2, "Executive/operator overview"),
    ResourceContract("markets", "v2:ui:snapshot:markets", "/api/v2/ui/markets", 5, "Compact market universe and eligibility"),
    ResourceContract("ai_brain", "v2:ui:snapshot:ai_brain", "/api/v2/ui/ai-brain", 10, "Trainer and model learning state"),
    ResourceContract("risk", "v2:ui:snapshot:risk", "/api/v2/ui/risk", 5, "Risk and live canary read-only state"),
    ResourceContract("portfolio", "v2:ui:snapshot:portfolio", "/api/v2/ui/portfolio", 2, "Canonical PnL and account scope"),
    ResourceContract("providers", "v2:ui:snapshot:providers", "/api/v2/ui/providers", 15, "Provider and ingestor actual-data cards"),
    ResourceContract("system_health", "v2:ui:snapshot:system_health", "/api/v2/ui/system-health", 5, "Backend/frontend/runtime service health"),
    ResourceContract("trader_cockpit", "v2:ui:snapshot:trader_cockpit", "/api/v2/ui/trader-cockpit", 2, "Current candidate and read-only trade plan"),
)


RESOURCE_ALIASES = {
    "ai-brain": "ai_brain",
    "ai": "ai_brain",
    "system-health": "system_health",
    "trader-cockpit": "trader_cockpit",
}


def normalize_resource_name(value: str) -> str:
    normalized = (value or "").strip().lower().replace("-", "_")
    return RESOURCE_ALIASES.get(normalized, normalized)


def resource_contracts() -> list[dict[str, object]]:
    return [
        {
            "name": item.name,
            "redis_key": item.redis_key,
            "endpoint": item.endpoint,
            "cadence_seconds": item.cadence_seconds,
            "description": item.description,
        }
        for item in RESOURCE_CONTRACTS
    ]


def resource_names() -> list[str]:
    return [item.name for item in RESOURCE_CONTRACTS]


def resource_key(name: str) -> str | None:
    normalized = normalize_resource_name(name)
    for item in RESOURCE_CONTRACTS:
        if item.name == normalized:
            return item.redis_key
    return None
