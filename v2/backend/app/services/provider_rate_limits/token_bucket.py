"""Token bucket limiter with deterministic clock injection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


Clock = Callable[[], float]


@dataclass(frozen=True)
class TokenBucketSnapshot:
    capacity: float
    refill_per_second: float
    tokens_available: float
    updated_at: float


class TokenBucket:
    """Simple token bucket.

    The bucket never allows more than ``capacity`` tokens and never consumes
    when there are insufficient tokens. It is intentionally in-memory; callers
    persist usage separately through a ledger.
    """

    def __init__(
        self,
        *,
        capacity: float,
        refill_per_second: float,
        clock: Clock | None = None,
        initial_tokens: float | None = None,
    ) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if refill_per_second < 0:
            raise ValueError("refill_per_second must be non-negative")
        self.capacity = float(capacity)
        self.refill_per_second = float(refill_per_second)
        self._clock = clock or _monotonic
        self._tokens = (
            float(initial_tokens)
            if initial_tokens is not None
            else float(capacity)
        )
        self._tokens = max(0.0, min(self.capacity, self._tokens))
        self._updated_at = float(self._clock())

    @classmethod
    def per_minute(
        cls,
        requests_per_minute: int | float,
        *,
        clock: Clock | None = None,
        initial_tokens: float | None = None,
    ) -> "TokenBucket":
        rpm = float(requests_per_minute)
        return cls(
            capacity=rpm,
            refill_per_second=rpm / 60.0,
            clock=clock,
            initial_tokens=initial_tokens,
        )

    def refill(self) -> None:
        now = float(self._clock())
        elapsed = max(0.0, now - self._updated_at)
        if elapsed:
            self._tokens = min(
                self.capacity,
                self._tokens + elapsed * self.refill_per_second,
            )
            self._updated_at = now

    def can_consume(self, amount: float = 1.0) -> bool:
        self.refill()
        return amount >= 0 and self._tokens >= amount

    def consume(self, amount: float = 1.0) -> bool:
        if amount < 0:
            raise ValueError("amount must be non-negative")
        self.refill()
        if self._tokens < amount:
            return False
        self._tokens -= amount
        return True

    def snapshot(self) -> TokenBucketSnapshot:
        self.refill()
        return TokenBucketSnapshot(
            capacity=self.capacity,
            refill_per_second=self.refill_per_second,
            tokens_available=self._tokens,
            updated_at=self._updated_at,
        )


def _monotonic() -> float:
    import time

    return time.monotonic()
