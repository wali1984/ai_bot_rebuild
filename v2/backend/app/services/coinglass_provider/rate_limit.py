"""CoinGlass token-bucket and account-limit handling."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from app.services.provider_rate_limits import BackoffPolicy, ProviderBackoff, TokenBucket

COINGLASS_PLAN = os.getenv("COINGLASS_PLAN", "standard")
COINGLASS_PUBLIC_LIMIT_PER_MINUTE = int(os.getenv("COINGLASS_PUBLIC_LIMIT_PER_MINUTE", "300"))
COINGLASS_NORMAL_LIMIT_PER_MINUTE = int(os.getenv("COINGLASS_NORMAL_LIMIT_PER_MINUTE", "210"))
COINGLASS_CATCHUP_LIMIT_PER_MINUTE = int(os.getenv("COINGLASS_CATCHUP_LIMIT_PER_MINUTE", "260"))
COINGLASS_HARD_LIMIT_PER_MINUTE = int(os.getenv("COINGLASS_HARD_LIMIT_PER_MINUTE", "285"))
COINGLASS_RESERVED_MANUAL_PER_MINUTE = int(os.getenv("COINGLASS_RESERVED_MANUAL_PER_MINUTE", "15"))
COINGLASS_RESERVED_HEALTH_PER_MINUTE = int(os.getenv("COINGLASS_RESERVED_HEALTH_PER_MINUTE", "5"))
COINGLASS_BACKOFF_ON_429_SECONDS = int(os.getenv("COINGLASS_BACKOFF_ON_429_SECONDS", "60"))
COINGLASS_BACKOFF_ON_5XX_SECONDS = int(os.getenv("COINGLASS_BACKOFF_ON_5XX_SECONDS", "30"))
COINGLASS_TIMEOUT_SECONDS = float(os.getenv("COINGLASS_TIMEOUT_SECONDS", "8"))
COINGLASS_MAX_CONCURRENT_REQUESTS = int(os.getenv("COINGLASS_MAX_CONCURRENT_REQUESTS", "5"))

LIMIT_SOURCE_OFFICIAL_PUBLIC_DOCS = "OFFICIAL_PUBLIC_DOCS"
LIMIT_SOURCE_ACCOUNT_HEADER_DISCOVERED = "ACCOUNT_HEADER_DISCOVERED"
LIMIT_SOURCE_ENV_OVERRIDE = "ENV_OVERRIDE"


@dataclass(frozen=True)
class CoinGlassLimit:
    requests_per_minute: int
    provider_limit_source: str
    public_limit_per_minute: int = COINGLASS_PUBLIC_LIMIT_PER_MINUTE
    normal_limit_per_minute: int = COINGLASS_NORMAL_LIMIT_PER_MINUTE
    hard_limit_per_minute: int = COINGLASS_HARD_LIMIT_PER_MINUTE
    manual_reserve_per_minute: int = COINGLASS_RESERVED_MANUAL_PER_MINUTE
    health_reserve_per_minute: int = COINGLASS_RESERVED_HEALTH_PER_MINUTE

    def as_dict(self) -> dict[str, object]:
        return {
            "requests_per_minute": self.requests_per_minute,
            "provider_limit_source": self.provider_limit_source,
            "public_limit_per_minute": self.public_limit_per_minute,
            "normal_limit_per_minute": self.normal_limit_per_minute,
            "hard_limit_per_minute": self.hard_limit_per_minute,
            "manual_reserve_per_minute": self.manual_reserve_per_minute,
            "health_reserve_per_minute": self.health_reserve_per_minute,
        }


class CoinGlassRateLimiter:
    """CoinGlass limiter capped below public plan limits."""

    def __init__(
        self,
        *,
        env: Mapping[str, str | None] | None = None,
        account_header_limit: int | None = None,
        clock=None,
    ) -> None:
        self.env = env or os.environ
        self.account_header_limit = account_header_limit
        self.limit = resolve_coinglass_limit(self.env, account_header_limit=account_header_limit)
        self.bucket = TokenBucket.per_minute(self.limit.requests_per_minute, clock=clock)
        self.backoff = ProviderBackoff(
            BackoffPolicy(
                rate_limited_seconds=COINGLASS_BACKOFF_ON_429_SECONDS,
                server_error_seconds=COINGLASS_BACKOFF_ON_5XX_SECONDS,
                auth_forbidden_seconds=COINGLASS_BACKOFF_ON_429_SECONDS,
                max_backoff_seconds=3600,
            ),
            clock=clock,
        )

    def allow_request(self, *, cost: int = 1) -> tuple[bool, str]:
        if self.backoff.is_active():
            return False, str(self.backoff.reason)
        if not self.bucket.consume(float(cost)):
            return False, "TOKEN_BUCKET_EMPTY"
        return True, "ALLOWED"

    def observe_response(self, status: int | None, headers: Mapping[str, object] | None = None) -> None:
        if headers:
            discovered = _int_header(headers, "API-KEY-MAX-LIMIT")
            if discovered:
                self.account_header_limit = discovered
                self.limit = resolve_coinglass_limit(self.env, account_header_limit=discovered)
                self.bucket.capacity = float(self.limit.requests_per_minute)
                self.bucket.refill_per_second = float(self.limit.requests_per_minute) / 60.0
        self.backoff.record_http_status(status)

    def as_dict(self) -> dict[str, object]:
        snap = self.bucket.snapshot()
        return {
            "schema_version": "coinglass_rate_limit_status_v1",
            "provider": "coinglass",
            **self.limit.as_dict(),
            "tokens_available": snap.tokens_available,
            "refill_per_second": snap.refill_per_second,
            "backoff": self.backoff.as_dict(),
            "timeout_seconds": COINGLASS_TIMEOUT_SECONDS,
            "max_concurrent_requests": COINGLASS_MAX_CONCURRENT_REQUESTS,
            "raw_key_exposed": False,
            "core_system_blocked": False,
        }


def resolve_coinglass_limit(
    env: Mapping[str, str | None],
    *,
    account_header_limit: int | None = None,
) -> CoinGlassLimit:
    if account_header_limit is not None and account_header_limit > 0:
        requested = int(account_header_limit)
        source = LIMIT_SOURCE_ACCOUNT_HEADER_DISCOVERED
    elif str(env.get("COINGLASS_LIMIT_PER_MINUTE_OVERRIDE") or "").strip():
        requested = int(str(env.get("COINGLASS_LIMIT_PER_MINUTE_OVERRIDE")))
        source = LIMIT_SOURCE_ENV_OVERRIDE
    else:
        requested = COINGLASS_PUBLIC_LIMIT_PER_MINUTE
        source = LIMIT_SOURCE_OFFICIAL_PUBLIC_DOCS
    usable = min(
        requested,
        COINGLASS_HARD_LIMIT_PER_MINUTE,
        max(1, requested - COINGLASS_RESERVED_MANUAL_PER_MINUTE),
    )
    return CoinGlassLimit(requests_per_minute=int(usable), provider_limit_source=source)


def classify_status(status: int | None) -> str:
    if status in {401, 402, 403}:
        return "CONFIGURED_BUT_UNAUTHORIZED_OR_UNSUBSCRIBED"
    if status == 429:
        return "RATE_LIMITED"
    if status is None:
        return "DEGRADED"
    if 200 <= status <= 299:
        return "READY"
    if 500 <= status <= 599:
        return "DEGRADED"
    return "UNAVAILABLE"


def dashboard_color(*, provider_enabled: bool, auth_status: str, actual_payload_count: int, stale: bool = False) -> str:
    if not provider_enabled or auth_status in {"CONFIGURED_BUT_UNAUTHORIZED_OR_UNSUBSCRIBED", "CONFIGURED_BUT_UNSUBSCRIBED_OR_FORBIDDEN"}:
        return "GRAY"
    if actual_payload_count > 0 and auth_status == "READY" and not stale:
        return "GREEN"
    if auth_status in {"RATE_LIMITED", "DEGRADED"} or stale:
        return "YELLOW"
    return "GRAY"


def _int_header(headers: Mapping[str, object], name: str) -> int | None:
    for key, value in headers.items():
        if str(key).lower() == name.lower():
            try:
                return int(str(value))
            except (TypeError, ValueError):
                return None
    return None
