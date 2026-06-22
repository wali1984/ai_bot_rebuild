"""Free-tier rate-limit scheduler for V2 alternative data.

This module creates a deterministic dry-run schedule. It never calls
provider APIs and never enables paid endpoints.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from v2.backend.app.services.alternative_data.provider_registry import (
    provider_definitions,
)


@dataclass(frozen=True)
class ProviderRateLimit:
    provider_id: str
    tier: str
    rate_limit_per_minute: int | None
    daily_request_budget: int | None
    cache_ttl_seconds: int | None
    per_symbol_cooldown_seconds: int | None
    paid_endpoint_enabled: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "tier": self.tier,
            "rate_limit_per_minute": self.rate_limit_per_minute,
            "daily_request_budget": self.daily_request_budget,
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "per_symbol_cooldown_seconds": self.per_symbol_cooldown_seconds,
            "paid_endpoint_enabled": self.paid_endpoint_enabled,
        }


def build_rate_limit_contract(
    *,
    alt_data_tier: str = "free",
    alt_data_enable_paid: bool = False,
    paid_endpoints_validated: bool = False,
) -> dict[str, Any]:
    paid_enabled = (
        alt_data_tier == "paid" and alt_data_enable_paid and paid_endpoints_validated
    )
    tier = "paid" if paid_enabled else "free"
    rows: list[ProviderRateLimit] = []
    for provider in provider_definitions():
        if tier == "paid":
            rows.append(
                ProviderRateLimit(
                    provider_id=provider.id,
                    tier=tier,
                    rate_limit_per_minute=provider.paid_rate_limit_per_minute,
                    daily_request_budget=provider.paid_daily_budget,
                    cache_ttl_seconds=provider.paid_cache_ttl_seconds,
                    per_symbol_cooldown_seconds=provider.paid_per_symbol_cooldown_seconds,
                    paid_endpoint_enabled=True,
                )
            )
        else:
            rows.append(
                ProviderRateLimit(
                    provider_id=provider.id,
                    tier="free",
                    rate_limit_per_minute=provider.free_rate_limit_per_minute,
                    daily_request_budget=provider.free_daily_budget,
                    cache_ttl_seconds=provider.free_cache_ttl_seconds,
                    per_symbol_cooldown_seconds=provider.free_per_symbol_cooldown_seconds,
                    paid_endpoint_enabled=False,
                )
            )
    return {
        "schema_version": "v2_alternative_data_rate_limit_contract_v1",
        "tier_requested": alt_data_tier,
        "alt_data_enable_paid_requested": bool(alt_data_enable_paid),
        "paid_endpoints_validated": bool(paid_endpoints_validated),
        "effective_tier": tier,
        "paid_tier_enabled": paid_enabled,
        "provider_limits": [row.as_dict() for row in rows],
        "provider_failure_isolation": True,
        "stale_but_safe_fallback": True,
        "provider_network_calls_attempted": False,
    }


def build_dry_run_schedule(symbols: tuple[str, ...]) -> list[dict[str, Any]]:
    schedule: list[dict[str, Any]] = []
    contract = build_rate_limit_contract()
    limits = {row["provider_id"]: row for row in contract["provider_limits"]}
    for provider_id in ("nansen", "lunarcrush"):
        limit = limits[provider_id]
        for rank, symbol in enumerate(symbols, start=1):
            schedule.append(
                {
                    "provider_id": provider_id,
                    "symbol": symbol,
                    "rank": rank,
                    "tier": "free",
                    "dry_run": True,
                    "network_call_allowed": False,
                    "cache_ttl_seconds": limit["cache_ttl_seconds"],
                    "per_symbol_cooldown_seconds": limit[
                        "per_symbol_cooldown_seconds"
                    ],
                }
            )
    return schedule

