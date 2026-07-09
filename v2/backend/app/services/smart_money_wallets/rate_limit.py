"""Moralis request and compute-unit limiter."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from app.services.provider_rate_limits import (
    BackoffPolicy,
    ComputeUnitBudget,
    ProviderBackoff,
    TokenBucket,
)

MORALIS_PLAN = os.getenv("MORALIS_PLAN", "starter")
MORALIS_PUBLIC_RPS = int(os.getenv("MORALIS_PUBLIC_RPS", "40"))
MORALIS_PUBLIC_CU_MONTHLY = int(os.getenv("MORALIS_PUBLIC_CU_MONTHLY", "2000000"))
MORALIS_DAILY_CU_BUDGET = int(os.getenv("MORALIS_DAILY_CU_BUDGET", "55000"))
MORALIS_DAILY_CU_RESERVE = int(os.getenv("MORALIS_DAILY_CU_RESERVE", "10000"))
MORALIS_NORMAL_RPS = int(os.getenv("MORALIS_NORMAL_RPS", "5"))
MORALIS_CATCHUP_RPS = int(os.getenv("MORALIS_CATCHUP_RPS", "10"))
MORALIS_HARD_RPS = int(os.getenv("MORALIS_HARD_RPS", "30"))
MORALIS_TIMEOUT_SECONDS = float(os.getenv("MORALIS_TIMEOUT_SECONDS", "10"))
MORALIS_BACKOFF_ON_429_SECONDS = int(os.getenv("MORALIS_BACKOFF_ON_429_SECONDS", "120"))
MORALIS_BACKOFF_ON_402_403_SECONDS = int(os.getenv("MORALIS_BACKOFF_ON_402_403_SECONDS", "3600"))


@dataclass(frozen=True)
class MoralisRequestDecision:
    allowed: bool
    reason: str
    estimated_cu: int
    actual_cu_from_headers: int | None = None

    def __iter__(self):
        yield self.allowed
        yield self.reason


class MoralisRateLimiter:
    def __init__(
        self,
        _ledger: object | None = None,
        *,
        used_today: int = 0,
        used_month: int = 0,
        rps: int | None = None,
        mode: str = "normal",
        clock=None,
    ) -> None:
        selected_rps = rps if rps is not None else _rps_for_mode(mode)
        self.rps = min(int(selected_rps), MORALIS_HARD_RPS, MORALIS_PUBLIC_RPS)
        self.bucket = TokenBucket(
            capacity=float(self.rps),
            refill_per_second=float(self.rps),
            clock=clock,
        )
        self.budget = ComputeUnitBudget(
            daily_budget=MORALIS_DAILY_CU_BUDGET,
            monthly_budget=MORALIS_PUBLIC_CU_MONTHLY,
            daily_reserve=MORALIS_DAILY_CU_RESERVE,
            used_today=used_today,
            used_month=used_month,
        )
        self.backoff = ProviderBackoff(
            BackoffPolicy(
                rate_limited_seconds=MORALIS_BACKOFF_ON_429_SECONDS,
                server_error_seconds=MORALIS_BACKOFF_ON_429_SECONDS,
                auth_forbidden_seconds=MORALIS_BACKOFF_ON_402_403_SECONDS,
                max_backoff_seconds=7200,
            ),
            clock=clock,
        )

    def allow_request(
        self,
        *,
        estimated_cu: int | None = None,
        cost_cu: int | None = None,
        lane: str | None = None,
    ) -> MoralisRequestDecision:
        del lane
        estimate = int(estimated_cu if estimated_cu is not None else cost_cu if cost_cu is not None else 0)
        if self.backoff.is_active():
            return MoralisRequestDecision(False, str(self.backoff.reason), estimate)
        budget_decision = self.budget.decide(estimate)
        if not budget_decision.allowed:
            return MoralisRequestDecision(False, budget_decision.reason, estimate)
        if not self.bucket.consume(1.0):
            return MoralisRequestDecision(False, "RPS_CAP", estimate)
        return MoralisRequestDecision(True, "ALLOWED", estimate)

    def charge(
        self,
        estimated_cu: int | None = None,
        *,
        headers: Mapping[str, object] | None = None,
        endpoint: str | None = None,
    ) -> int:
        del endpoint
        actual = moralis_cu_from_headers(headers or {}) or int(estimated_cu or 0)
        self.budget.charge(actual)
        return actual

    def observe_response(self, status: int | None) -> str:
        self.backoff.record_http_status(status)
        return classify_status(status)

    def as_dict(self) -> dict[str, object]:
        snap = self.bucket.snapshot()
        return {
            "schema_version": "moralis_compute_budget_status_v1",
            "provider": "moralis",
            "plan": MORALIS_PLAN,
            "public_rps": MORALIS_PUBLIC_RPS,
            "normal_rps": MORALIS_NORMAL_RPS,
            "catchup_rps": MORALIS_CATCHUP_RPS,
            "hard_rps": MORALIS_HARD_RPS,
            "current_rps": self.rps,
            "tokens_available": snap.tokens_available,
            "timeout_seconds": MORALIS_TIMEOUT_SECONDS,
            "compute_budget": self.budget.as_dict(),
            "backoff": self.backoff.as_dict(),
            "raw_key_exposed": False,
            "core_system_blocked": False,
        }


def moralis_cu_from_headers(headers: Mapping[str, object]) -> int | None:
    for name in (
        "x-moralis-compute-units",
        "x-compute-units",
        "x-records-charged",
    ):
        for key, value in headers.items():
            if str(key).lower() != name:
                continue
            try:
                parsed = int(float(str(value)))
            except (TypeError, ValueError):
                return None
            return parsed * 10 if name == "x-records-charged" else parsed
    return None


def _rps_for_mode(mode: str) -> int:
    normalized = str(mode or "normal").strip().lower()
    if normalized == "catchup":
        return MORALIS_CATCHUP_RPS
    if normalized == "hard":
        return MORALIS_HARD_RPS
    return MORALIS_NORMAL_RPS


def classify_status(status: int | None) -> str:
    if status in {401, 402, 403}:
        return "CONFIGURED_BUT_UNSUBSCRIBED_OR_FORBIDDEN"
    if status == 429:
        return "RATE_LIMITED"
    if status is None:
        return "DEGRADED"
    if 200 <= status <= 299:
        return "READY"
    if 500 <= status <= 599:
        return "DEGRADED"
    return "UNAVAILABLE"
