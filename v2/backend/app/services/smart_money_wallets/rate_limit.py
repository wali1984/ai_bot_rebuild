"""Moralis request and compute-unit limiter."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Mapping

from app.services.provider_rate_limits import (
    BackoffPolicy,
    ComputeUnitBudget,
    ProviderBackoff,
    TokenBucket,
)
from app.services.smart_money_wallets.cu_budget import MoralisCuBudget

BACKOFF_STATE_KEY = "v2:provider:moralis:backoff"

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
        redis_client: Any | None = None,
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
        # Persistent CU ledger (authoritative when Redis is available). Rehydrate the
        # in-memory budget from the durable month/day counters so a process restart
        # continues real spend instead of resetting to a fresh 2M month.
        self.redis = redis_client
        self.cu = MoralisCuBudget(redis_client) if redis_client is not None else None
        self._pending_reserve = 0
        if self.cu is not None:
            used_today = self.cu.day_spent()
            used_month = self.cu.month_spent()
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
        # Persisted backoff survives restarts: a 402/403 penalty must not be forgotten
        # by a process bounce and resume hammering an unsubscribed endpoint.
        persisted = self._persisted_backoff_reason()
        if persisted is not None:
            return MoralisRequestDecision(False, persisted, estimate)
        if self.backoff.is_active():
            return MoralisRequestDecision(False, str(self.backoff.reason), estimate)
        budget_decision = self.budget.decide(estimate)
        if not budget_decision.allowed:
            return MoralisRequestDecision(False, budget_decision.reason, estimate)
        # Authoritative persistent gate (both the 45k/day sub-cap AND the 2M/month cap).
        if self.cu is not None and not self.cu.can_spend(estimate):
            return MoralisRequestDecision(False, "CU_BUDGET_DAILY_OR_MONTHLY_EXCEEDED", estimate)
        if not self.bucket.consume(1.0):
            return MoralisRequestDecision(False, "RPS_CAP", estimate)
        # All checks passed -> RESERVE the estimate BEFORE the call (atomic Redis
        # INCRBY) so a concurrent poller cannot also pass the same budget check.
        if self.cu is not None:
            self.cu.charge(estimate)
            self._pending_reserve = estimate
            self.budget.charge(estimate)
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
        if self._pending_reserve:
            # Reserved path (Redis): reconcile the reservation to the real header CU.
            delta = int(actual) - int(self._pending_reserve)
            if self.cu is not None and delta:
                self.cu.charge(delta)
            self.budget.charge(delta)
            self._pending_reserve = 0
        else:
            # Non-reserved path (no Redis / legacy): charge actual after the fact.
            self.budget.charge(int(actual))
        return int(actual)

    def refund_pending(self) -> int:
        """Release a pre-call reservation when the request did not succeed, so a
        failed/denied call does not permanently consume budget."""
        refunded = int(self._pending_reserve)
        if refunded:
            if self.cu is not None:
                self.cu.charge(-refunded)
            self.budget.charge(-refunded)
            self._pending_reserve = 0
        return refunded

    def observe_response(self, status: int | None) -> str:
        self.backoff.record_http_status(status)
        self._persist_backoff(status)
        return classify_status(status)

    def _persist_backoff(self, status: int | None) -> None:
        if self.redis is None:
            return
        penalty = _penalty_seconds_for_status(status)
        if penalty <= 0:
            return
        try:
            self.redis.set(
                BACKOFF_STATE_KEY,
                json.dumps(
                    {
                        "until_epoch": time.time() + penalty,
                        "reason": classify_status(status),
                        "http_status": status,
                    }
                ),
                ex=penalty + 60,
            )
        except Exception:
            pass

    def _persisted_backoff_reason(self) -> str | None:
        if self.redis is None:
            return None
        try:
            raw = self.redis.get(BACKOFF_STATE_KEY)
        except Exception:
            return None
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        try:
            state = json.loads(str(raw))
        except (TypeError, ValueError):
            return None
        if not isinstance(state, Mapping):
            return None
        try:
            until = float(state.get("until_epoch") or 0.0)
        except (TypeError, ValueError):
            return None
        if until <= time.time():
            return None
        return f"PERSISTED_BACKOFF:{state.get('reason') or 'BACKOFF'}"

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
            "persistent_cu_ledger": self._persistent_ledger_snapshot(),
            "cu_ledger_persistent": self.cu is not None,
            "pending_reserve_cu": self._pending_reserve,
            "backoff": self.backoff.as_dict(),
            "raw_key_exposed": False,
            "core_system_blocked": False,
        }

    def _persistent_ledger_snapshot(self) -> dict[str, object] | None:
        if self.cu is None:
            return None
        return {
            "monthly_limit_cu": self.cu.monthly_limit,
            "month_spent_cu": self.cu.month_spent(),
            "remaining_month_cu": self.cu.remaining_month(),
            "day_spent_cu": self.cu.day_spent(),
            "remaining_today_cu": self.cu.remaining_today(),
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


def _penalty_seconds_for_status(status: int | None) -> int:
    if status in {401, 402, 403}:
        return MORALIS_BACKOFF_ON_402_403_SECONDS
    if status == 429 or (status is not None and 500 <= status <= 599):
        return MORALIS_BACKOFF_ON_429_SECONDS
    return 0


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
