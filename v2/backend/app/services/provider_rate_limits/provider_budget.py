"""Compute-unit and request-budget helpers for optional providers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    reason: str
    cost: int
    used_today: int
    used_month: int
    remaining_today: int
    remaining_month: int


class ComputeUnitBudget:
    """Local compute-unit guard.

    This class deliberately does not know provider semantics. It enforces
    daily and monthly caps and a daily reserve; usage persistence is handled by
    the caller or ``JsonUsageLedger``.
    """

    def __init__(
        self,
        *,
        daily_budget: int,
        monthly_budget: int,
        daily_reserve: int = 0,
        used_today: int = 0,
        used_month: int = 0,
    ) -> None:
        if daily_budget <= 0 or monthly_budget <= 0:
            raise ValueError("budgets must be positive")
        if daily_reserve < 0:
            raise ValueError("daily_reserve must be non-negative")
        self.daily_budget = int(daily_budget)
        self.monthly_budget = int(monthly_budget)
        self.daily_reserve = int(daily_reserve)
        self.used_today = max(0, int(used_today))
        self.used_month = max(0, int(used_month))

    @property
    def spendable_today(self) -> int:
        return max(0, self.daily_budget - self.daily_reserve)

    @property
    def remaining_today(self) -> int:
        return max(0, self.spendable_today - self.used_today)

    @property
    def remaining_month(self) -> int:
        return max(0, self.monthly_budget - self.used_month)

    def decide(self, cost: int) -> BudgetDecision:
        cost = max(0, int(cost))
        if cost > self.remaining_month:
            return self._decision(False, "MONTHLY_CU_BUDGET_EXHAUSTED", cost)
        if cost > self.remaining_today:
            return self._decision(False, "DAILY_CU_BUDGET_EXHAUSTED", cost)
        return self._decision(True, "BUDGET_AVAILABLE", cost)

    def charge(self, cost: int) -> BudgetDecision:
        decision = self.decide(cost)
        if decision.allowed:
            self.used_today += int(cost)
            self.used_month += int(cost)
            return self._decision(True, "BUDGET_CHARGED", int(cost))
        return decision

    def _decision(self, allowed: bool, reason: str, cost: int) -> BudgetDecision:
        return BudgetDecision(
            allowed=allowed,
            reason=reason,
            cost=cost,
            used_today=self.used_today,
            used_month=self.used_month,
            remaining_today=self.remaining_today,
            remaining_month=self.remaining_month,
        )

    def as_dict(self) -> dict[str, int]:
        return {
            "daily_budget": self.daily_budget,
            "monthly_budget": self.monthly_budget,
            "daily_reserve": self.daily_reserve,
            "used_today": self.used_today,
            "used_month": self.used_month,
            "remaining_today": self.remaining_today,
            "remaining_month": self.remaining_month,
        }
