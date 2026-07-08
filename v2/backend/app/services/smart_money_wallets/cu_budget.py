"""Moralis Compute-Unit budget manager.

Plan limit: 2,000,000 CU per calendar month. The manager tracks spend in
Redis, derives a dynamic daily allowance from the REMAINING month budget and
remaining days (so early overspend self-corrects), and refuses polls that
would exceed the day's allowance. A safety factor keeps headroom for ad-hoc
operator queries.

Keys:
  v2:provider:moralis:cu_usage:{YYYY-MM}       total CU spent this month
  v2:provider:moralis:cu_usage:{YYYY-MM-DD}    total CU spent today
  v2:provider:moralis:cu_budget_status         published status snapshot
"""

from __future__ import annotations

import calendar
import json
from datetime import datetime, timezone
from typing import Any

MONTHLY_CU_LIMIT = 2_000_000
DAILY_SAFETY_FACTOR = 0.80  # spend at most 80% of the derived daily allowance

MONTH_KEY = "v2:provider:moralis:cu_usage:{month}"
DAY_KEY = "v2:provider:moralis:cu_usage:{day}"
STATUS_KEY = "v2:provider:moralis:cu_budget_status"


class MoralisCuBudget:
    def __init__(self, redis_client: Any, *, monthly_limit: int = MONTHLY_CU_LIMIT):
        self.r = redis_client
        self.monthly_limit = int(monthly_limit)

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _month_key(self, now: datetime) -> str:
        return MONTH_KEY.format(month=now.strftime("%Y-%m"))

    def _day_key(self, now: datetime) -> str:
        return DAY_KEY.format(day=now.strftime("%Y-%m-%d"))

    def month_spent(self) -> int:
        now = self._now()
        return int(self.r.get(self._month_key(now)) or 0)

    def day_spent(self) -> int:
        now = self._now()
        return int(self.r.get(self._day_key(now)) or 0)

    def remaining_month(self) -> int:
        return max(0, self.monthly_limit - self.month_spent())

    def daily_allowance(self) -> int:
        """Remaining month budget spread over remaining days, with safety factor."""
        now = self._now()
        days_in_month = calendar.monthrange(now.year, now.month)[1]
        remaining_days = max(1, days_in_month - now.day + 1)
        return int(self.remaining_month() / remaining_days * DAILY_SAFETY_FACTOR)

    def remaining_today(self) -> int:
        return max(0, self.daily_allowance() - self.day_spent())

    def can_spend(self, cost_cu: int) -> bool:
        return cost_cu <= self.remaining_today() and cost_cu <= self.remaining_month()

    def charge(self, cost_cu: int, *, endpoint: str = "") -> None:
        now = self._now()
        mk, dk = self._month_key(now), self._day_key(now)
        pipe = self.r.pipeline()
        pipe.incrby(mk, int(cost_cu))
        # keep month counters ~62 days, day counters ~3 days
        pipe.expire(mk, 62 * 86400)
        pipe.incrby(dk, int(cost_cu))
        pipe.expire(dk, 3 * 86400)
        pipe.execute()

    def publish_status(self, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        now = self._now()
        status = {
            "schema_version": "moralis_cu_budget_status_v1",
            "generated_utc": now.isoformat(timespec="seconds"),
            "monthly_limit_cu": self.monthly_limit,
            "month_spent_cu": self.month_spent(),
            "remaining_month_cu": self.remaining_month(),
            "daily_allowance_cu": self.daily_allowance(),
            "day_spent_cu": self.day_spent(),
            "remaining_today_cu": self.remaining_today(),
            "safety_factor": DAILY_SAFETY_FACTOR,
            "raw_key_exposed": False,
            **(extra or {}),
        }
        self.r.set(STATUS_KEY, json.dumps(status), ex=6 * 3600)
        return status
