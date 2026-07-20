"""Moralis request limiter backed by the durable CU reservation authority."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.services.provider_rate_limits import (
    BackoffPolicy,
    ComputeUnitBudget,
    ProviderBackoff,
    TokenBucket,
)
from app.services.smart_money_wallets.cu_budget import (
    MoralisCuBudget,
    MoralisCuReconciliationOutcome,
    MoralisCuReservationOutcome,
    reservation_as_dict,
)

BACKOFF_STATE_KEY = "v2:provider:moralis:backoff"
DISTRIBUTED_RPS_WINDOW_PREFIX = "v2:provider:moralis:rps_window"

_DISTRIBUTED_RPS_SCRIPT = """
local now = redis.call('TIME')
local window_key = KEYS[1] .. ':' .. now[1]
local count = redis.call('INCR', window_key)
if count == 1 then
  redis.call('EXPIRE', window_key, 2)
end
if count > tonumber(ARGV[1]) then
  return {0, count}
end
return {1, count}
"""

MORALIS_DOCUMENTED_PUBLIC_RPS_LIMIT = 40
MORALIS_DOCUMENTED_MONTHLY_CU_LIMIT = 2_000_000
# A fixed UTC-second limiter can overlap five buckets inside an arbitrary
# rolling four-second provider window. Thirty per bucket bounds that worst case
# at 150 requests, below the documented 160-request four-second allowance.
MORALIS_FIXED_WINDOW_SAFE_RPS_LIMIT = 30
MORALIS_PLAN = os.getenv("MORALIS_PLAN", "starter")
MORALIS_PUBLIC_RPS = min(
    MORALIS_DOCUMENTED_PUBLIC_RPS_LIMIT,
    max(1, int(os.getenv("MORALIS_PUBLIC_RPS", "40"))),
)
MORALIS_PUBLIC_CU_MONTHLY = min(
    MORALIS_DOCUMENTED_MONTHLY_CU_LIMIT,
    max(1, int(os.getenv("MORALIS_PUBLIC_CU_MONTHLY", "2000000"))),
)
MORALIS_DAILY_CU_BUDGET = min(
    MORALIS_PUBLIC_CU_MONTHLY,
    max(0, int(os.getenv("MORALIS_DAILY_CU_BUDGET", "55000"))),
)
MORALIS_DAILY_CU_RESERVE = min(
    MORALIS_DAILY_CU_BUDGET,
    max(0, int(os.getenv("MORALIS_DAILY_CU_RESERVE", "10000"))),
)
MORALIS_NORMAL_RPS = int(os.getenv("MORALIS_NORMAL_RPS", "5"))
MORALIS_CATCHUP_RPS = int(os.getenv("MORALIS_CATCHUP_RPS", "10"))
MORALIS_HARD_RPS = min(
    MORALIS_FIXED_WINDOW_SAFE_RPS_LIMIT,
    max(1, int(os.getenv("MORALIS_HARD_RPS", "30"))),
)
MORALIS_TIMEOUT_SECONDS = float(os.getenv("MORALIS_TIMEOUT_SECONDS", "10"))
MORALIS_BACKOFF_ON_429_SECONDS = int(os.getenv("MORALIS_BACKOFF_ON_429_SECONDS", "120"))
MORALIS_BACKOFF_ON_402_403_SECONDS = int(os.getenv("MORALIS_BACKOFF_ON_402_403_SECONDS", "3600"))


@dataclass(frozen=True)
class MoralisRequestDecision:
    allowed: bool
    reason: str
    estimated_cu: int
    reservation: MoralisCuReservationOutcome | None = None
    actual_cu_from_headers: int | None = None

    def __iter__(self) -> Iterator[bool | str]:
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
        clock: Callable[[], float] | None = None,
        ledger_now_factory: Callable[[], datetime] | None = None,
        require_persistent_ledger: bool | None = None,
    ) -> None:
        del _ledger
        selected_rps = rps if rps is not None else _rps_for_mode(mode)
        self.rps = max(
            1,
            min(
                int(selected_rps),
                MORALIS_HARD_RPS,
                MORALIS_PUBLIC_RPS,
                MORALIS_FIXED_WINDOW_SAFE_RPS_LIMIT,
            ),
        )
        self.bucket = TokenBucket(
            capacity=float(self.rps),
            refill_per_second=float(self.rps),
            clock=clock,
        )
        self.redis = redis_client
        self.require_persistent_ledger = (
            redis_client is not None
            if require_persistent_ledger is None
            else bool(require_persistent_ledger)
        )
        self.cu = (
            MoralisCuBudget(
                redis_client,
                monthly_limit=min(
                    MORALIS_PUBLIC_CU_MONTHLY,
                    MORALIS_DOCUMENTED_MONTHLY_CU_LIMIT,
                ),
                daily_hard_cap=max(0, MORALIS_DAILY_CU_BUDGET - MORALIS_DAILY_CU_RESERVE),
                now_factory=ledger_now_factory,
            )
            if redis_client is not None
            else None
        )
        self._pending_reservation: MoralisCuReservationOutcome | None = None
        self._pending_actual_cu: int | None = None
        self._last_reconciliation: MoralisCuReconciliationOutcome | None = None
        self._ledger_health_reason = "READY" if self.cu is not None else "CU_LEDGER_NOT_CONFIGURED"
        self._distributed_rps_health_reason = (
            "READY" if redis_client is not None else "RPS_LEDGER_NOT_CONFIGURED"
        )
        if self.cu is not None:
            snapshot = self.cu.snapshot()
            if snapshot.available:
                used_today = int(snapshot.day_spent_cu or 0)
                used_month = int(snapshot.month_spent_cu or 0)
            else:
                self._ledger_health_reason = snapshot.reason
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
        try:
            estimate = int(
                estimated_cu if estimated_cu is not None else cost_cu if cost_cu is not None else 0
            )
        except (TypeError, ValueError, OverflowError):
            return MoralisRequestDecision(False, "INVALID_CU_AMOUNT", 0)
        if estimate <= 0:
            return MoralisRequestDecision(False, "INVALID_CU_AMOUNT", estimate)
        retry_reason = self._retry_pending_reconciliation()
        if retry_reason is not None:
            return MoralisRequestDecision(False, retry_reason, estimate)
        if self._pending_reservation is not None:
            return MoralisRequestDecision(False, "CU_REQUEST_ALREADY_IN_FLIGHT", estimate)
        persisted = self._persisted_backoff_reason()
        if persisted is not None:
            return MoralisRequestDecision(False, persisted, estimate)
        if self.backoff.is_active():
            return MoralisRequestDecision(False, str(self.backoff.reason), estimate)
        if not self.bucket.consume(1.0):
            return MoralisRequestDecision(False, "RPS_CAP", estimate)

        # Every Redis-backed Moralis caller shares this provider-wide window.
        # The local bucket still smooths a single process; this atomic guard
        # prevents canonical, bootstrap, and any operator process from each
        # independently consuming the advertised RPS allowance.
        if self.redis is not None:
            distributed_rps_reason = self._consume_distributed_rps()
            if distributed_rps_reason is not None:
                return MoralisRequestDecision(False, distributed_rps_reason, estimate)

        if self.cu is None:
            if self.require_persistent_ledger:
                self._ledger_health_reason = "CU_LEDGER_REQUIRED"
                return MoralisRequestDecision(False, "CU_LEDGER_REQUIRED", estimate)
            budget_decision = self.budget.decide(estimate)
            if not budget_decision.allowed:
                return MoralisRequestDecision(False, budget_decision.reason, estimate)
            return MoralisRequestDecision(True, "ALLOWED_LOCAL_ONLY", estimate)

        reservation = self.cu.reserve(estimate)
        if not reservation.allowed:
            self._ledger_health_reason = reservation.reason
            return MoralisRequestDecision(False, reservation.reason, estimate, reservation)
        self._ledger_health_reason = "READY"
        self._pending_reservation = reservation
        self._sync_local_budget(
            day_spent=reservation.day_spent_cu,
            month_spent=reservation.month_spent_cu,
        )
        return MoralisRequestDecision(True, "ALLOWED_RESERVED", estimate, reservation)

    def reconcile_response(
        self,
        *,
        reservation: MoralisCuReservationOutcome | None,
        headers: Mapping[str, object] | None,
        estimated_cu: int,
        http_status: int,
    ) -> MoralisCuReconciliationOutcome:
        """Account every received HTTP response, independent of status class.

        A valid provider CU header is authoritative, including zero.  If no
        usable header is present, the conservative estimate remains charged.
        """
        del http_status
        header_cu = moralis_cu_from_headers(headers or {})
        reserved_cu = int(reservation.reserved_cu if reservation is not None else estimated_cu)
        actual_cu = header_cu if header_cu is not None else reserved_cu

        if self.cu is None:
            decision = self.budget.charge(actual_cu)
            return MoralisCuReconciliationOutcome(
                applied=decision.allowed,
                reason="LOCAL_ONLY_RECONCILED" if decision.allowed else decision.reason,
                reserved_cu=reserved_cu,
                actual_cu=actual_cu,
                delta_cu=actual_cu - reserved_cu,
                ledger_available=False,
                idempotent=False,
                day_spent_cu=self.budget.used_today,
                month_spent_cu=self.budget.used_month,
            )
        if reservation is None:
            self._ledger_health_reason = "CU_RESERVATION_NOT_FOUND"
            return MoralisCuReconciliationOutcome(
                applied=False,
                reason="CU_RESERVATION_NOT_FOUND",
                reserved_cu=0,
                actual_cu=actual_cu,
                delta_cu=actual_cu,
                ledger_available=True,
                idempotent=False,
                day_spent_cu=None,
                month_spent_cu=None,
            )

        self._pending_actual_cu = actual_cu
        return self._reconcile_persistent(reservation, actual_cu=actual_cu)

    def retain_ambiguous_reservation(
        self,
        reservation: MoralisCuReservationOutcome | None,
    ) -> MoralisCuReconciliationOutcome | None:
        """Settle an ambiguous request at its conservative reserved estimate."""
        if self.cu is None or reservation is None:
            return None
        self._pending_actual_cu = reservation.reserved_cu
        return self._reconcile_persistent(
            reservation,
            actual_cu=reservation.reserved_cu,
        )

    def charge(
        self,
        estimated_cu: int | None = None,
        *,
        headers: Mapping[str, object] | None = None,
        endpoint: str | None = None,
    ) -> int:
        """Compatibility wrapper; new callers should use ``reconcile_response``."""
        del endpoint
        estimate = int(estimated_cu or 0)
        header_cu = moralis_cu_from_headers(headers or {})
        actual = header_cu if header_cu is not None else estimate
        if self.cu is None:
            self.budget.charge(actual)
            return actual
        self.reconcile_response(
            reservation=self._pending_reservation,
            headers=headers,
            estimated_cu=estimate,
            http_status=200,
        )
        return actual

    def refund_pending(self, *, request_was_not_sent: bool = False) -> int:
        """Refund only when the caller can prove no HTTP request was sent.

        Timeouts and transport exceptions are ambiguous and therefore return
        zero while leaving the reservation charged.
        """
        reservation = self._pending_reservation
        if not request_was_not_sent or reservation is None or self.cu is None:
            return 0
        self._pending_actual_cu = 0
        outcome = self._reconcile_persistent(reservation, actual_cu=0)
        if not outcome.applied:
            return 0
        return reservation.reserved_cu

    def observe_response(self, status: int | None) -> str:
        self.backoff.record_http_status(status)
        self._persist_backoff(status)
        return classify_status(status)

    def as_dict(self) -> dict[str, object]:
        snap = self.bucket.snapshot()
        persistent = self._persistent_ledger_snapshot()
        ledger_available = bool(persistent and persistent.get("ledger_available"))
        reconciliation_pending = self._pending_actual_cu is not None
        request_in_flight = self._pending_reservation is not None
        return {
            "schema_version": "moralis_compute_budget_status_v2",
            "provider": "moralis",
            "plan": MORALIS_PLAN,
            "public_rps": MORALIS_PUBLIC_RPS,
            "normal_rps": MORALIS_NORMAL_RPS,
            "catchup_rps": MORALIS_CATCHUP_RPS,
            "hard_rps": MORALIS_HARD_RPS,
            "current_rps": self.rps,
            "self_imposed_rps_window_seconds": 1,
            "self_imposed_rps_policy": "FIXED_UTC_SECOND_ATOMIC_REDIS_WINDOW",
            "provider_documented_rps_window_seconds": 4,
            "provider_documented_rps_semantics": "REQUESTS_PER_SECOND_OVER_ROLLING_FOUR_SECONDS",
            "fixed_window_rolling_safe_rps_limit": (
                MORALIS_FIXED_WINDOW_SAFE_RPS_LIMIT
            ),
            "tokens_available": snap.tokens_available,
            "distributed_rps_guard": self.redis is not None,
            "distributed_rps_guard_required": self.redis is not None,
            "distributed_rps_guard_reason": self._distributed_rps_health_reason,
            "timeout_seconds": MORALIS_TIMEOUT_SECONDS,
            "compute_budget": self.budget.as_dict(),
            "persistent_cu_ledger": persistent,
            "cu_ledger_persistent": self.cu is not None,
            "cu_ledger_required": self.require_persistent_ledger,
            "cu_ledger_available": ledger_available,
            "cu_ledger_reason": self._ledger_health_reason,
            "provider_polling_blocked": self.require_persistent_ledger
            and (
                not ledger_available
                or reconciliation_pending
                or request_in_flight
                or self._ledger_health_reason != "READY"
                or self._distributed_rps_health_reason != "READY"
            ),
            "pending_reservation": reservation_as_dict(self._pending_reservation),
            "request_in_flight": request_in_flight,
            "reconciliation_pending": reconciliation_pending,
            "ambiguous_delivery_reservation_retained": True,
            "atomic_cross_process_reservation": self.cu is not None,
            "backoff": self.backoff.as_dict(),
            "raw_key_exposed": False,
            "core_system_blocked": False,
        }

    def _consume_distributed_rps(self) -> str | None:
        if self.redis is None:
            return None
        try:
            raw = self.redis.eval(
                _DISTRIBUTED_RPS_SCRIPT,
                1,
                DISTRIBUTED_RPS_WINDOW_PREFIX,
                self.rps,
            )
            if not isinstance(raw, list | tuple) or len(raw) != 2:
                self._distributed_rps_health_reason = "RPS_LEDGER_INVALID_RESPONSE"
                return self._distributed_rps_health_reason
            allowed = int(raw[0]) == 1
        except Exception:
            self._distributed_rps_health_reason = "RPS_LEDGER_UNAVAILABLE"
            return self._distributed_rps_health_reason
        self._distributed_rps_health_reason = "READY"
        return None if allowed else "DISTRIBUTED_RPS_CAP"

    def _persistent_ledger_snapshot(self) -> dict[str, object] | None:
        if self.cu is None:
            return None
        snapshot = self.cu.snapshot()
        if snapshot.available:
            if self._pending_actual_cu is None and self._pending_reservation is None:
                self._ledger_health_reason = "READY"
            self._sync_local_budget(
                day_spent=snapshot.day_spent_cu,
                month_spent=snapshot.month_spent_cu,
            )
        return {
            "ledger_available": snapshot.available,
            "reason": snapshot.reason,
            "monthly_limit_cu": snapshot.monthly_limit_cu,
            "month_spent_cu": snapshot.month_spent_cu,
            "remaining_month_cu": snapshot.remaining_month_cu,
            "daily_limit_cu": snapshot.daily_limit_cu,
            "day_spent_cu": snapshot.day_spent_cu,
            "remaining_today_cu": snapshot.remaining_today_cu,
        }

    def _sync_local_budget(
        self,
        *,
        day_spent: int | None,
        month_spent: int | None,
    ) -> None:
        if day_spent is not None:
            self.budget.used_today = max(0, int(day_spent))
        if month_spent is not None:
            self.budget.used_month = max(0, int(month_spent))

    def _retry_pending_reconciliation(self) -> str | None:
        if self._pending_actual_cu is None:
            return None
        if self.cu is None or self._pending_reservation is None:
            self._ledger_health_reason = "CU_RECONCILIATION_STATE_INVALID"
            return self._ledger_health_reason
        outcome = self._reconcile_persistent(
            self._pending_reservation,
            actual_cu=self._pending_actual_cu,
        )
        return None if outcome.applied else f"CU_RECONCILIATION_PENDING:{outcome.reason}"

    def _reconcile_persistent(
        self,
        reservation: MoralisCuReservationOutcome,
        *,
        actual_cu: int,
    ) -> MoralisCuReconciliationOutcome:
        if self.cu is None:
            raise RuntimeError("persistent reconciliation requires a CU ledger")
        outcome = self.cu.reconcile(reservation, actual_cu=actual_cu)
        self._last_reconciliation = outcome
        if outcome.applied:
            self._ledger_health_reason = "READY"
            self._pending_actual_cu = None
            self._sync_local_budget(
                day_spent=outcome.day_spent_cu,
                month_spent=outcome.month_spent_cu,
            )
            if self._pending_reservation == reservation:
                self._pending_reservation = None
        else:
            self._ledger_health_reason = outcome.reason
        return outcome

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
            # CU reservations remain authoritative; backoff persistence is diagnostic.
            return

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
            if parsed < 0:
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
