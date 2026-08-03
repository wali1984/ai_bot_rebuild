"""Provider limiter hard rules (named per goal spec)."""

from __future__ import annotations

import subprocess

from v2.backend.app.services.coinglass_provider.rate_limit import (
    COINGLASS_HARD_LIMIT_PER_MINUTE,
    CoinGlassRateLimiter,
)
from v2.backend.app.services.smart_money_wallets.rate_limit import (
    MORALIS_DAILY_CU_BUDGET,
    MORALIS_DAILY_CU_RESERVE,
    MoralisRateLimiter,
)


class _FrozenClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def test_coinglass_never_exceeds_285_per_min() -> None:
    clock = _FrozenClock()
    limiter = CoinGlassRateLimiter(clock=clock)
    granted = sum(1 for _ in range(400) if limiter.allow_request()[0])
    assert granted <= COINGLASS_HARD_LIMIT_PER_MINUTE
    assert granted <= limiter.limit.requests_per_minute


def test_coinglass_429_enters_backoff() -> None:
    clock = _FrozenClock()
    limiter = CoinGlassRateLimiter(clock=clock)
    limiter.observe_response(429)
    ok, reason = limiter.allow_request()
    assert ok is False
    assert "429" in reason or "RATE" in reason.upper()


def test_coinglass_403_is_gray_nonblocking() -> None:
    clock = _FrozenClock()
    limiter = CoinGlassRateLimiter(clock=clock)
    limiter.observe_response(403)
    status = limiter.as_dict()
    # provider may pause itself, but it must never claim to block the core
    assert status.get("core_system_blocked") in (False, None)


def test_moralis_never_exceeds_daily_cu_budget() -> None:
    clock = _FrozenClock()
    limiter = MoralisRateLimiter(clock=clock)
    scheduler_cap = MORALIS_DAILY_CU_BUDGET - MORALIS_DAILY_CU_RESERVE
    spent = 0
    for _ in range(200):
        decision = limiter.allow_request(estimated_cu=1000)
        if not getattr(decision, "allowed", decision[0] if isinstance(decision, tuple) else False):
            reason = getattr(decision, "reason", "")
            if "RPS" in str(reason).upper():
                clock.advance(1.0)
                continue
            break
        limiter.charge(estimated_cu=1000)
        spent += 1000
    assert spent <= scheduler_cap


def test_moralis_never_exceeds_hard_rps() -> None:
    clock = _FrozenClock()
    limiter = MoralisRateLimiter(rps=100, clock=clock)  # asks above hard cap
    granted = 0
    for _ in range(100):
        decision = limiter.allow_request(estimated_cu=1)
        if getattr(decision, "allowed", False):
            granted += 1
    assert limiter.rps <= 30  # hard cap honored at construction
    assert granted <= limiter.rps


def test_moralis_402_is_gray_nonblocking() -> None:
    clock = _FrozenClock()
    limiter = MoralisRateLimiter(clock=clock)
    limiter.observe_response(402)
    assert limiter.as_dict()["core_system_blocked"] is False


def test_provider_keys_never_logged() -> None:
    out = subprocess.run(
        "rg -n 'print.*API_KEY|logger.*API_KEY|logging.*API_KEY' "
        "v2/backend/app/services/coinglass_provider "
        "v2/backend/app/services/smart_money_wallets "
        "v2/backend/app/services/provider_rate_limits || true",
        shell=True, capture_output=True, text=True,
        cwd="/home/wali/Desktop/AI BOT REBUILD",
    )
    assert out.stdout.strip() == ""
