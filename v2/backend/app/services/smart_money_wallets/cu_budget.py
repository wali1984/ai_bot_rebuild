"""Durable, fail-closed Moralis compute-unit budget authority.

The Redis ledger is authoritative across processes and restarts.  A request
must reserve its estimated compute units before any HTTP call.  The reservation
atomically covers both the UTC-day and UTC-month counters; a response may then
reconcile that reservation to a provider-reported actual cost.  If delivery is
ambiguous (for example, a timeout), the reservation is intentionally retained.

Keys:
  v2:provider:moralis:cu_usage:{YYYY-MM}       total reserved/spent CU in month
  v2:provider:moralis:cu_usage:{YYYY-MM-DD}    total reserved/spent CU in day
  v2:provider:moralis:cu_budget_status         bounded status snapshot
"""

from __future__ import annotations

import calendar
import json
import math
import os
import secrets
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

MONTHLY_CU_LIMIT = 2_000_000
DAILY_SAFETY_FACTOR = 0.80
DAILY_SAFETY_BPS = 8_000
DAILY_HARD_CAP = max(
    0,
    int(os.getenv("MORALIS_DAILY_CU_BUDGET", "55000"))
    - int(os.getenv("MORALIS_DAILY_CU_RESERVE", "10000")),
)

DAY_COUNTER_RETENTION_SECONDS = 2 * 86_400
MONTH_COUNTER_RETENTION_SECONDS = 31 * 86_400
MAX_DAY_COUNTER_TTL_SECONDS = 3 * 86_400
MAX_MONTH_COUNTER_TTL_SECONDS = 63 * 86_400
STATUS_TTL_SECONDS = 6 * 3_600

MONTH_KEY = "v2:provider:moralis:cu_usage:{month}"
DAY_KEY = "v2:provider:moralis:cu_usage:{day}"
RESERVATION_KEY = "v2:provider:moralis:cu_reservation:{reservation_id}"
STATUS_KEY = "v2:provider:moralis:cu_budget_status"

_RESERVE_SCRIPT = """
local requested = tonumber(ARGV[1])
local monthly_limit = tonumber(ARGV[2])
local daily_hard_cap = tonumber(ARGV[3])
local safety_bps = tonumber(ARGV[4])
local remaining_days = tonumber(ARGV[5])
local day_ttl = tonumber(ARGV[6])
local month_ttl = tonumber(ARGV[7])
local reservation_value = ARGV[8]
local reservation_ttl = tonumber(ARGV[9])

if not requested or requested <= 0 or requested % 1 ~= 0
  or not monthly_limit or monthly_limit <= 0 or monthly_limit % 1 ~= 0
  or not daily_hard_cap or daily_hard_cap <= 0
  or not safety_bps or safety_bps <= 0 or safety_bps > 10000
  or not remaining_days or remaining_days <= 0
  or not day_ttl or day_ttl <= 0
  or not month_ttl or month_ttl <= 0
  or not reservation_ttl or reservation_ttl <= 0
  or not reservation_value or reservation_value == '' then
  return {-1, 3, 0, 0, 0}
end
if redis.call('EXISTS', KEYS[3]) == 1 then
  return {-1, 6, 0, 0, 0}
end

local raw_day = redis.call('GET', KEYS[1])
local raw_month = redis.call('GET', KEYS[2])
local day_spent = tonumber(raw_day or '0')
local month_spent = tonumber(raw_month or '0')
if not day_spent or not month_spent
  or day_spent < 0 or month_spent < day_spent
  or day_spent % 1 ~= 0 or month_spent % 1 ~= 0 then
  return {-1, 4, 0, 0, 0}
end

-- Derive today's TOTAL adaptive cap from spend before today.  Subtracting
-- today's spend from remaining_month and then comparing the total day counter
-- would count the same CU twice and prematurely halve the allowance.
local spent_before_today = month_spent - day_spent
local remaining_for_today = math.max(0, monthly_limit - spent_before_today)
local dynamic_daily = math.floor(
  (remaining_for_today * safety_bps) / (math.max(1, remaining_days) * 10000)
)
local daily_limit = math.min(dynamic_daily, daily_hard_cap)

if month_spent + requested > monthly_limit then
  return {0, 1, day_spent, month_spent, daily_limit}
end
if day_spent + requested > daily_limit then
  return {0, 2, day_spent, month_spent, daily_limit}
end

local new_day = redis.call('INCRBY', KEYS[1], requested)
local new_month = redis.call('INCRBY', KEYS[2], requested)
redis.call('EXPIRE', KEYS[1], day_ttl)
redis.call('EXPIRE', KEYS[2], month_ttl)
redis.call('SET', KEYS[3], reservation_value, 'EX', reservation_ttl)
return {1, 0, new_day, new_month, daily_limit}
"""

_RECONCILE_SCRIPT = """
local reserved = tonumber(ARGV[1])
local actual = tonumber(ARGV[2])
local max_day_ttl = tonumber(ARGV[3])
local max_month_ttl = tonumber(ARGV[4])
local reservation_ttl = tonumber(ARGV[5])
if not reserved or reserved <= 0 or reserved % 1 ~= 0
  or not actual or actual < 0 or actual % 1 ~= 0
  or not max_day_ttl or max_day_ttl <= 0
  or not max_month_ttl or max_month_ttl <= 0
  or not reservation_ttl or reservation_ttl <= 0 then
  return {-1, 3, 0, 0}
end

local reservation_state = redis.call('GET', KEYS[3])
local pending_state = 'P:' .. tostring(reserved)
local settled_state = 'S:' .. tostring(actual)
if not reservation_state then
  return {-1, 5, 0, 0}
end
if reservation_state == settled_state then
  local existing_day = tonumber(redis.call('GET', KEYS[1]) or '-1')
  local existing_month = tonumber(redis.call('GET', KEYS[2]) or '-1')
  if existing_day < 0 or existing_month < existing_day
    or existing_day % 1 ~= 0 or existing_month % 1 ~= 0 then
    return {-1, 4, 0, 0}
  end
  return {2, 0, existing_day, existing_month}
end
if reservation_state ~= pending_state then
  return {-1, 7, 0, 0}
end

local raw_day = redis.call('GET', KEYS[1])
local raw_month = redis.call('GET', KEYS[2])
if not raw_day or not raw_month then
  return {-1, 5, 0, 0}
end
local day_spent = tonumber(raw_day)
local month_spent = tonumber(raw_month)
if not day_spent or not month_spent
  or day_spent < reserved or month_spent < day_spent
  or day_spent % 1 ~= 0 or month_spent % 1 ~= 0 then
  return {-1, 4, 0, 0}
end

local delta = actual - reserved
local new_day = day_spent + delta
local new_month = month_spent + delta
if new_day < 0 or new_month < 0 then
  return {-1, 4, 0, 0}
end
if delta ~= 0 then
  new_day = redis.call('INCRBY', KEYS[1], delta)
  new_month = redis.call('INCRBY', KEYS[2], delta)
end

local day_ttl = redis.call('TTL', KEYS[1])
if day_ttl < 1 or day_ttl > max_day_ttl then
  redis.call('EXPIRE', KEYS[1], max_day_ttl)
end
local month_ttl = redis.call('TTL', KEYS[2])
if month_ttl < 1 or month_ttl > max_month_ttl then
  redis.call('EXPIRE', KEYS[2], max_month_ttl)
end
redis.call('SET', KEYS[3], settled_state, 'EX', reservation_ttl)
return {1, 0, new_day, new_month}
"""

_SNAPSHOT_SCRIPT = """
local raw_day = redis.call('GET', KEYS[1])
local raw_month = redis.call('GET', KEYS[2])
local day_spent = tonumber(raw_day or '0')
local month_spent = tonumber(raw_month or '0')
if not day_spent or not month_spent
  or day_spent < 0 or month_spent < day_spent
  or day_spent % 1 ~= 0 or month_spent % 1 ~= 0 then
  return {-1, 4, 0, 0}
end
return {1, 0, day_spent, month_spent}
"""

_REASON_BY_CODE = {
    0: "OK",
    1: "MONTHLY_CU_BUDGET_EXHAUSTED",
    2: "DAILY_CU_BUDGET_EXHAUSTED",
    3: "INVALID_CU_AMOUNT",
    4: "CU_LEDGER_CORRUPT",
    5: "CU_RESERVATION_NOT_FOUND",
    6: "CU_RESERVATION_ID_COLLISION",
    7: "CU_RECONCILIATION_CONFLICT",
}


@dataclass(frozen=True)
class MoralisCuSnapshot:
    available: bool
    reason: str
    day_spent_cu: int | None
    month_spent_cu: int | None
    daily_limit_cu: int | None
    monthly_limit_cu: int
    remaining_today_cu: int | None
    remaining_month_cu: int | None


@dataclass(frozen=True)
class MoralisCuReservationOutcome:
    allowed: bool
    reason: str
    requested_cu: int
    reserved_cu: int
    ledger_available: bool
    reservation_id: str | None
    reservation_key: str | None
    day_key: str | None
    month_key: str | None
    day_spent_cu: int | None
    month_spent_cu: int | None
    daily_limit_cu: int | None
    monthly_limit_cu: int
    day_ttl_seconds: int | None
    month_ttl_seconds: int | None


@dataclass(frozen=True)
class MoralisCuReconciliationOutcome:
    applied: bool
    reason: str
    reserved_cu: int
    actual_cu: int
    delta_cu: int
    ledger_available: bool
    idempotent: bool
    day_spent_cu: int | None
    month_spent_cu: int | None


class MoralisCuBudget:
    """Redis-backed CU ledger with atomic reserve and reconciliation."""

    def __init__(
        self,
        redis_client: Any,
        *,
        monthly_limit: int = MONTHLY_CU_LIMIT,
        daily_hard_cap: int = DAILY_HARD_CAP,
        daily_safety_bps: int = DAILY_SAFETY_BPS,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.r = redis_client
        self.monthly_limit = int(monthly_limit)
        self.daily_hard_cap = max(0, int(daily_hard_cap))
        self.daily_safety_bps = min(10_000, max(1, int(daily_safety_bps)))
        self._now_factory = now_factory or (lambda: datetime.now(UTC))
        self._legacy_pending_reservation: MoralisCuReservationOutcome | None = None
        if self.monthly_limit <= 0:
            raise ValueError("monthly_limit must be positive")

    def _now(self) -> datetime:
        now = self._now_factory()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        return now.astimezone(UTC)

    def _month_key(self, now: datetime) -> str:
        return MONTH_KEY.format(month=now.strftime("%Y-%m"))

    def _day_key(self, now: datetime) -> str:
        return DAY_KEY.format(day=now.strftime("%Y-%m-%d"))

    def reserve(self, cost_cu: int) -> MoralisCuReservationOutcome:
        """Atomically reserve ``cost_cu`` against both active-period caps."""
        try:
            requested = int(cost_cu)
        except (TypeError, ValueError, OverflowError):
            requested = 0
        now = self._now()
        context = self._period_context(now)
        reservation_id = secrets.token_hex(16)
        reservation_key = RESERVATION_KEY.format(reservation_id=reservation_id)
        if isinstance(cost_cu, bool) or requested <= 0:
            return self._reservation_outcome(
                allowed=False,
                reason="INVALID_CU_AMOUNT",
                requested=requested,
                context=context,
            )
        if self.daily_hard_cap <= 0:
            return self._reservation_outcome(
                allowed=False,
                reason="CU_BUDGET_CONFIGURATION_INVALID",
                requested=requested,
                context=context,
            )
        try:
            raw = self.r.eval(
                _RESERVE_SCRIPT,
                3,
                context["day_key"],
                context["month_key"],
                reservation_key,
                requested,
                self.monthly_limit,
                self.daily_hard_cap,
                self.daily_safety_bps,
                context["remaining_days"],
                context["day_ttl_seconds"],
                context["month_ttl_seconds"],
                f"P:{requested}",
                context["day_ttl_seconds"],
            )
            status, reason_code, day_spent, month_spent, daily_limit = _integer_result(raw, 5)
        except Exception:  # Redis is optional to the core system; polling fails closed.
            return self._reservation_outcome(
                allowed=False,
                reason="CU_LEDGER_UNAVAILABLE",
                requested=requested,
                context=context,
                ledger_available=False,
            )
        reason = _REASON_BY_CODE.get(reason_code, "CU_LEDGER_INVALID_RESPONSE")
        allowed = status == 1 and reason_code == 0
        if status not in {0, 1}:
            allowed = False
        if status not in {-1, 0, 1} or reason_code not in _REASON_BY_CODE:
            reason = "CU_LEDGER_INVALID_RESPONSE"
        return self._reservation_outcome(
            allowed=allowed,
            reason="RESERVED" if allowed else reason,
            requested=requested,
            context=context,
            ledger_available=reason != "CU_LEDGER_INVALID_RESPONSE",
            day_spent=day_spent,
            month_spent=month_spent,
            daily_limit=daily_limit,
            reservation_id=reservation_id,
            reservation_key=reservation_key,
        )

    def reconcile(
        self,
        reservation: MoralisCuReservationOutcome,
        *,
        actual_cu: int,
    ) -> MoralisCuReconciliationOutcome:
        """Atomically reconcile an accepted reservation to provider-reported CU.

        The original reservation keys are mandatory.  This ensures a response
        crossing UTC midnight is charged to the period in which it was sent.
        """
        try:
            actual = int(actual_cu)
        except (TypeError, ValueError, OverflowError):
            actual = -1
        if (
            isinstance(actual_cu, bool)
            or actual < 0
            or not reservation.allowed
            or reservation.reserved_cu <= 0
            or not reservation.reservation_key
            or not reservation.day_key
            or not reservation.month_key
        ):
            return MoralisCuReconciliationOutcome(
                applied=False,
                reason="INVALID_CU_RECONCILIATION",
                reserved_cu=max(0, int(reservation.reserved_cu)),
                actual_cu=actual,
                delta_cu=actual - max(0, int(reservation.reserved_cu)),
                ledger_available=True,
                idempotent=False,
                day_spent_cu=None,
                month_spent_cu=None,
            )
        try:
            raw = self.r.eval(
                _RECONCILE_SCRIPT,
                3,
                reservation.day_key,
                reservation.month_key,
                reservation.reservation_key,
                reservation.reserved_cu,
                actual,
                min(
                    MAX_DAY_COUNTER_TTL_SECONDS,
                    max(1, int(reservation.day_ttl_seconds or 1)),
                ),
                min(
                    MAX_MONTH_COUNTER_TTL_SECONDS,
                    max(1, int(reservation.month_ttl_seconds or 1)),
                ),
                min(
                    MAX_DAY_COUNTER_TTL_SECONDS,
                    max(1, int(reservation.day_ttl_seconds or 1)),
                ),
            )
            status, reason_code, day_spent, month_spent = _integer_result(raw, 4)
        except Exception:
            return MoralisCuReconciliationOutcome(
                applied=False,
                reason="CU_LEDGER_UNAVAILABLE_RESERVATION_RETAINED",
                reserved_cu=reservation.reserved_cu,
                actual_cu=actual,
                delta_cu=actual - reservation.reserved_cu,
                ledger_available=False,
                idempotent=False,
                day_spent_cu=None,
                month_spent_cu=None,
            )
        reason = _REASON_BY_CODE.get(reason_code, "CU_LEDGER_INVALID_RESPONSE")
        applied = status in {1, 2} and reason_code == 0
        if status not in {-1, 1, 2} or reason_code not in _REASON_BY_CODE:
            reason = "CU_LEDGER_INVALID_RESPONSE"
            applied = False
        return MoralisCuReconciliationOutcome(
            applied=applied,
            reason="ALREADY_RECONCILED" if status == 2 else "RECONCILED" if applied else reason,
            reserved_cu=reservation.reserved_cu,
            actual_cu=actual,
            delta_cu=actual - reservation.reserved_cu,
            ledger_available=reason != "CU_LEDGER_INVALID_RESPONSE",
            idempotent=status == 2 and applied,
            day_spent_cu=day_spent if applied else None,
            month_spent_cu=month_spent if applied else None,
        )

    def snapshot(self) -> MoralisCuSnapshot:
        if self.daily_hard_cap <= 0:
            return self._unavailable_snapshot("CU_BUDGET_CONFIGURATION_INVALID")
        now = self._now()
        day_key = self._day_key(now)
        month_key = self._month_key(now)
        try:
            raw = self.r.eval(_SNAPSHOT_SCRIPT, 2, day_key, month_key)
            status, reason_code, day_spent, month_spent = _integer_result(raw, 4)
        except Exception:
            return self._unavailable_snapshot("CU_LEDGER_UNAVAILABLE")
        if status != 1 or reason_code != 0:
            return self._unavailable_snapshot(
                _REASON_BY_CODE.get(reason_code, "CU_LEDGER_INVALID_RESPONSE")
            )
        daily_limit = self._daily_limit(now, month_spent, day_spent)
        return MoralisCuSnapshot(
            available=True,
            reason="READY",
            day_spent_cu=day_spent,
            month_spent_cu=month_spent,
            daily_limit_cu=daily_limit,
            monthly_limit_cu=self.monthly_limit,
            remaining_today_cu=max(0, daily_limit - day_spent),
            remaining_month_cu=max(0, self.monthly_limit - month_spent),
        )

    def month_spent(self) -> int:
        snapshot = self.snapshot()
        return int(snapshot.month_spent_cu or 0) if snapshot.available else 0

    def day_spent(self) -> int:
        snapshot = self.snapshot()
        return int(snapshot.day_spent_cu or 0) if snapshot.available else 0

    def remaining_month(self) -> int:
        snapshot = self.snapshot()
        return int(snapshot.remaining_month_cu or 0) if snapshot.available else 0

    def daily_allowance(self) -> int:
        snapshot = self.snapshot()
        return int(snapshot.daily_limit_cu or 0) if snapshot.available else 0

    def remaining_today(self) -> int:
        snapshot = self.snapshot()
        return int(snapshot.remaining_today_cu or 0) if snapshot.available else 0

    def can_spend(self, cost_cu: int) -> bool:
        """Compatibility gate that atomically pre-reserves the requested CU.

        Older pollers call ``can_spend(cost)`` immediately followed by
        ``charge(cost)``.  A read-only check would reintroduce the cross-process
        race, so this method holds the accepted reservation for ``charge``.
        """
        if self._legacy_pending_reservation is not None:
            return False
        outcome = self.reserve(cost_cu)
        if not outcome.allowed:
            return False
        self._legacy_pending_reservation = outcome
        return True

    def charge(
        self,
        cost_cu: int,
        *,
        endpoint: str = "",
    ) -> MoralisCuReservationOutcome:
        """Compatibility reserve for legacy pre-request pollers.

        The ``endpoint`` label is accepted for API compatibility.  The CU was
        already reserved by ``can_spend`` when that method preceded this call;
        otherwise this method performs the atomic reservation itself.
        """
        del endpoint
        try:
            requested = int(cost_cu)
        except (TypeError, ValueError, OverflowError):
            requested = 0
        pending = self._legacy_pending_reservation
        if pending is not None and pending.reserved_cu == requested:
            self._legacy_pending_reservation = None
            # Mark the durable receipt settled at the conservative estimate.
            # The counter does not change and ambiguous delivery stays charged.
            self.reconcile(pending, actual_cu=pending.reserved_cu)
            return pending
        return self.reserve(requested)

    def publish_status(self, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        now = self._now()
        snapshot = self.snapshot()
        status = {
            "schema_version": "moralis_cu_budget_status_v2",
            "generated_utc": now.isoformat(timespec="seconds"),
            "ledger_available": snapshot.available,
            "ledger_reason": snapshot.reason,
            "monthly_limit_cu": snapshot.monthly_limit_cu,
            "month_spent_cu": snapshot.month_spent_cu,
            "remaining_month_cu": snapshot.remaining_month_cu,
            "daily_allowance_cu": snapshot.daily_limit_cu,
            "daily_hard_cap_cu": self.daily_hard_cap,
            "day_spent_cu": snapshot.day_spent_cu,
            "remaining_today_cu": snapshot.remaining_today_cu,
            "safety_factor": self.daily_safety_bps / 10_000,
            "atomic_cross_process_reservation": True,
            "ambiguous_delivery_reservation_retained": True,
            "raw_key_exposed": False,
            **(extra or {}),
        }
        try:
            self.r.set(STATUS_KEY, json.dumps(status), ex=STATUS_TTL_SECONDS)
        except Exception:
            status["status_publish_succeeded"] = False
        else:
            status["status_publish_succeeded"] = True
        return status

    def _reservation_outcome(
        self,
        *,
        allowed: bool,
        reason: str,
        requested: int,
        context: dict[str, Any],
        ledger_available: bool = True,
        day_spent: int | None = None,
        month_spent: int | None = None,
        daily_limit: int | None = None,
        reservation_id: str | None = None,
        reservation_key: str | None = None,
    ) -> MoralisCuReservationOutcome:
        return MoralisCuReservationOutcome(
            allowed=allowed,
            reason=reason,
            requested_cu=requested,
            reserved_cu=requested if allowed else 0,
            ledger_available=ledger_available,
            reservation_id=reservation_id if allowed else None,
            reservation_key=reservation_key if allowed else None,
            day_key=str(context["day_key"]) if allowed else None,
            month_key=str(context["month_key"]) if allowed else None,
            day_spent_cu=day_spent,
            month_spent_cu=month_spent,
            daily_limit_cu=daily_limit,
            monthly_limit_cu=self.monthly_limit,
            day_ttl_seconds=int(context["day_ttl_seconds"]) if allowed else None,
            month_ttl_seconds=int(context["month_ttl_seconds"]) if allowed else None,
        )

    def _period_context(self, now: datetime) -> dict[str, Any]:
        tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
        if now.month == 12:
            next_month = datetime(now.year + 1, 1, 1, tzinfo=UTC)
        else:
            next_month = datetime(now.year, now.month + 1, 1, tzinfo=UTC)
        day_ttl = math.ceil((tomorrow - now).total_seconds()) + DAY_COUNTER_RETENTION_SECONDS
        month_ttl = math.ceil((next_month - now).total_seconds()) + MONTH_COUNTER_RETENTION_SECONDS
        days_in_month = calendar.monthrange(now.year, now.month)[1]
        return {
            "day_key": self._day_key(now),
            "month_key": self._month_key(now),
            "remaining_days": max(1, days_in_month - now.day + 1),
            "day_ttl_seconds": min(MAX_DAY_COUNTER_TTL_SECONDS, max(1, day_ttl)),
            "month_ttl_seconds": min(MAX_MONTH_COUNTER_TTL_SECONDS, max(1, month_ttl)),
        }

    def _daily_limit(self, now: datetime, month_spent: int, day_spent: int) -> int:
        days_in_month = calendar.monthrange(now.year, now.month)[1]
        remaining_days = max(1, days_in_month - now.day + 1)
        spent_before_today = max(0, int(month_spent) - int(day_spent))
        remaining_for_today = max(0, self.monthly_limit - spent_before_today)
        dynamic = (remaining_for_today * self.daily_safety_bps) // (remaining_days * 10_000)
        return min(dynamic, self.daily_hard_cap)

    def _unavailable_snapshot(self, reason: str) -> MoralisCuSnapshot:
        return MoralisCuSnapshot(
            available=False,
            reason=reason,
            day_spent_cu=None,
            month_spent_cu=None,
            daily_limit_cu=None,
            monthly_limit_cu=self.monthly_limit,
            remaining_today_cu=None,
            remaining_month_cu=None,
        )


def reservation_as_dict(reservation: MoralisCuReservationOutcome | None) -> dict[str, Any] | None:
    """Serialize a reservation outcome without exposing internal Redis keys."""
    if reservation is None:
        return None
    payload = asdict(reservation)
    payload.pop("reservation_key", None)
    payload.pop("day_key", None)
    payload.pop("month_key", None)
    return payload


def _integer_result(raw: Any, expected_length: int) -> tuple[int, ...]:
    if not isinstance(raw, list | tuple) or len(raw) != expected_length:
        raise ValueError("invalid Redis ledger response")
    return tuple(int(value) for value in raw)
