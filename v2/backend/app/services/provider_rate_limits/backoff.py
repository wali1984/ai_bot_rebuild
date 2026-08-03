"""Provider backoff state for rate-limit and subscription failures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


Clock = Callable[[], float]


@dataclass(frozen=True)
class BackoffPolicy:
    rate_limited_seconds: int
    server_error_seconds: int
    auth_forbidden_seconds: int
    max_backoff_seconds: int = 3600


class ProviderBackoff:
    def __init__(
        self,
        policy: BackoffPolicy,
        *,
        clock: Clock | None = None,
    ) -> None:
        self.policy = policy
        self._clock = clock or _monotonic
        self.until_epoch_seconds = 0.0
        self.reason = "NONE"
        self.consecutive_failures = 0

    def is_active(self) -> bool:
        return float(self._clock()) < self.until_epoch_seconds

    def seconds_remaining(self) -> int:
        return max(0, int(round(self.until_epoch_seconds - float(self._clock()))))

    def clear(self) -> None:
        self.until_epoch_seconds = 0.0
        self.reason = "NONE"
        self.consecutive_failures = 0

    def record_http_status(self, status: int | None) -> None:
        if status is None:
            self._start("TIMEOUT_OR_NETWORK_ERROR", self.policy.server_error_seconds)
            return
        if status == 429:
            self._start("RATE_LIMITED", self.policy.rate_limited_seconds)
            return
        if status in {401, 402, 403}:
            self._start(
                "CONFIGURED_BUT_UNAUTHORIZED_OR_UNSUBSCRIBED",
                self.policy.auth_forbidden_seconds,
            )
            return
        if 500 <= status <= 599:
            self._start("SERVER_ERROR", self.policy.server_error_seconds)
            return
        if 200 <= status <= 299:
            self.clear()

    def _start(self, reason: str, base_seconds: int) -> None:
        self.consecutive_failures += 1
        multiplier = 2 ** max(0, self.consecutive_failures - 1)
        duration = min(
            int(self.policy.max_backoff_seconds),
            max(1, int(base_seconds)) * multiplier,
        )
        self.reason = reason
        self.until_epoch_seconds = float(self._clock()) + duration

    def as_dict(self) -> dict[str, object]:
        return {
            "active": self.is_active(),
            "reason": self.reason,
            "seconds_remaining": self.seconds_remaining(),
            "consecutive_failures": self.consecutive_failures,
        }


def _monotonic() -> float:
    import time

    return time.monotonic()
