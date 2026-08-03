from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import httpx
import pytest
import redis

from v2.backend.app.services.smart_money_wallets import rate_limit as rate_limit_module
from v2.backend.app.services.smart_money_wallets.client import MoralisClient
from v2.backend.app.services.smart_money_wallets.cu_budget import (
    DAY_KEY,
    MAX_DAY_COUNTER_TTL_SECONDS,
    MAX_MONTH_COUNTER_TTL_SECONDS,
    MONTH_KEY,
    MoralisCuBudget,
)
from v2.backend.app.services.smart_money_wallets.endpoint_registry import (
    moralis_endpoint_registry,
)
from v2.backend.app.services.smart_money_wallets.rate_limit import MoralisRateLimiter

VALID_TOKEN_ADDRESS = "0x" + ("1" * 40)


def test_environment_overrides_cannot_raise_documented_rps_or_monthly_cu_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rate_limit_module, "MORALIS_PUBLIC_RPS", 1_000)
    monkeypatch.setattr(rate_limit_module, "MORALIS_HARD_RPS", 1_000)
    monkeypatch.setattr(rate_limit_module, "MORALIS_PUBLIC_CU_MONTHLY", 99_000_000)

    limiter = MoralisRateLimiter(redis_client=_FailingRedis(), rps=1_000)

    assert limiter.rps == rate_limit_module.MORALIS_FIXED_WINDOW_SAFE_RPS_LIMIT
    assert limiter.cu is not None
    assert (
        limiter.cu.monthly_limit
        == rate_limit_module.MORALIS_DOCUMENTED_MONTHLY_CU_LIMIT
    )


class _MutableUtcClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class _StaticHttpClient:
    def __init__(self, response: httpx.Response | Exception) -> None:
        self.response = response
        self.calls = 0

    @contextmanager
    def stream(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
    ) -> Iterator[httpx.Response]:
        self.calls += 1
        if isinstance(self.response, Exception):
            raise self.response
        response = httpx.Response(
            self.response.status_code,
            headers=self.response.headers,
            stream=httpx.ByteStream(self.response.content),
            request=httpx.Request(method, url, headers=headers),
        )
        try:
            yield response
        finally:
            response.close()


class _FailingRedis:
    def get(self, *_args: Any, **_kwargs: Any) -> Any:
        raise ConnectionError("redis unavailable")

    def eval(self, *_args: Any, **_kwargs: Any) -> Any:
        raise ConnectionError("redis unavailable")

    def set(self, *_args: Any, **_kwargs: Any) -> Any:
        raise ConnectionError("redis unavailable")


class _ApplyThenLoseReconcileReplyRedis:
    """Simulate Redis applying reconciliation before the client loses its reply."""

    def __init__(self, delegate: redis.Redis) -> None:
        self.delegate = delegate
        self.reply_lost = False

    def eval(self, script: str, *args: Any) -> Any:
        if "local reservation_state" in script and not self.reply_lost:
            self.delegate.eval(script, *args)
            self.reply_lost = True
            raise ConnectionError("reconciliation reply lost after apply")
        return self.delegate.eval(script, *args)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)


@pytest.fixture()
def redis_socket(tmp_path: Path) -> Iterator[str]:
    executable = shutil.which("redis-server")
    if executable is None:
        pytest.skip("redis-server is required for the atomic Lua contract test")
    assert executable is not None
    socket_path = str(tmp_path / "redis.sock")
    process = subprocess.Popen(  # noqa: S603 - fixed local test executable/arguments
        [
            executable,
            "--port",
            "0",
            "--save",
            "",
            "--appendonly",
            "no",
            "--unixsocket",
            socket_path,
            "--unixsocketperm",
            "700",
            "--dir",
            str(tmp_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 5.0
    client: redis.Redis | None = None
    while time.monotonic() < deadline:
        try:
            client = _redis_client(socket_path)
            if client.ping():
                break
        except (OSError, redis.RedisError):
            time.sleep(0.02)
    else:
        process.terminate()
        process.wait(timeout=5)
        pytest.fail("ephemeral redis-server did not become ready")
    assert client is not None
    client.flushdb()
    try:
        yield socket_path
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _redis_client(socket_path: str) -> redis.Redis:
    return redis.Redis(unix_socket_path=socket_path, decode_responses=True)


def _token_transfers_spec():
    return next(
        spec for spec in moralis_endpoint_registry() if spec.endpoint_id == "token_transfers"
    )


def test_atomic_reserve_blocks_concurrent_clients_at_daily_cap(redis_socket: str) -> None:
    now = datetime(2026, 7, 1, 12, tzinfo=UTC)

    def reserve() -> bool:
        authority = MoralisCuBudget(
            _redis_client(redis_socket),
            monthly_limit=100_000,
            daily_hard_cap=100,
            daily_safety_bps=10_000,
            now_factory=lambda: now,
        )
        return authority.reserve(10).allowed

    with ThreadPoolExecutor(max_workers=20) as pool:
        allowed = list(pool.map(lambda _index: reserve(), range(40)))

    redis_client = _redis_client(redis_socket)
    day_key = DAY_KEY.format(day="2026-07-01")
    month_key = MONTH_KEY.format(month="2026-07")
    assert sum(allowed) == 10
    assert int(redis_client.get(day_key) or 0) == 100
    assert int(redis_client.get(month_key) or 0) == 100
    assert 0 < redis_client.ttl(day_key) <= MAX_DAY_COUNTER_TTL_SECONDS
    assert 0 < redis_client.ttl(month_key) <= MAX_MONTH_COUNTER_TTL_SECONDS


def test_atomic_reserve_enforces_monthly_cap_across_clients(redis_socket: str) -> None:
    now = datetime(2026, 7, 31, 12, tzinfo=UTC)

    def reserve() -> tuple[bool, str]:
        outcome = MoralisCuBudget(
            _redis_client(redis_socket),
            monthly_limit=100,
            daily_hard_cap=1_000,
            daily_safety_bps=10_000,
            now_factory=lambda: now,
        ).reserve(10)
        return outcome.allowed, outcome.reason

    with ThreadPoolExecutor(max_workers=20) as pool:
        outcomes = list(pool.map(lambda _index: reserve(), range(40)))

    assert sum(allowed for allowed, _reason in outcomes) == 10
    assert {reason for allowed, reason in outcomes if not allowed} == {
        "MONTHLY_CU_BUDGET_EXHAUSTED"
    }
    redis_client = _redis_client(redis_socket)
    assert int(redis_client.get(MONTH_KEY.format(month="2026-07")) or 0) == 100


def test_reservation_receipt_and_all_ledger_keys_have_bounded_expiry(
    redis_socket: str,
) -> None:
    now = datetime(2026, 7, 19, 12, tzinfo=UTC)
    redis_client = _redis_client(redis_socket)
    reservation = MoralisCuBudget(
        redis_client,
        now_factory=lambda: now,
    ).reserve(50)

    assert reservation.allowed is True
    assert reservation.reservation_id
    assert reservation.reservation_key
    assert 0 < redis_client.ttl(reservation.reservation_key) <= MAX_DAY_COUNTER_TTL_SECONDS
    assert 0 < redis_client.ttl(reservation.day_key) <= MAX_DAY_COUNTER_TTL_SECONDS
    assert 0 < redis_client.ttl(reservation.month_key) <= MAX_MONTH_COUNTER_TTL_SECONDS


def test_corrupt_non_integer_counters_fail_closed_without_partial_write(
    redis_socket: str,
) -> None:
    now = datetime(2026, 7, 19, 12, tzinfo=UTC)
    redis_client = _redis_client(redis_socket)
    day_key = DAY_KEY.format(day="2026-07-19")
    month_key = MONTH_KEY.format(month="2026-07")
    redis_client.set(day_key, "1.5")
    redis_client.set(month_key, "1.5")

    outcome = MoralisCuBudget(
        redis_client,
        now_factory=lambda: now,
    ).reserve(50)

    assert outcome.allowed is False
    assert outcome.reason == "CU_LEDGER_CORRUPT"
    assert redis_client.get(day_key) == "1.5"
    assert redis_client.get(month_key) == "1.5"


def test_zero_daily_cap_configuration_fails_closed_without_ledger_write(
    redis_socket: str,
) -> None:
    now = datetime(2026, 7, 19, 12, tzinfo=UTC)
    redis_client = _redis_client(redis_socket)
    authority = MoralisCuBudget(
        redis_client,
        daily_hard_cap=0,
        now_factory=lambda: now,
    )

    outcome = authority.reserve(50)

    assert outcome.allowed is False
    assert outcome.reason == "CU_BUDGET_CONFIGURATION_INVALID"
    assert authority.snapshot().reason == "CU_BUDGET_CONFIGURATION_INVALID"
    assert redis_client.get(DAY_KEY.format(day="2026-07-19")) is None
    assert redis_client.get(MONTH_KEY.format(month="2026-07")) is None


@pytest.mark.parametrize("cost_cu", [None, "not-a-number", True])
def test_malformed_reservation_cost_fails_closed_without_raising(
    redis_socket: str,
    cost_cu: object,
) -> None:
    redis_client = _redis_client(redis_socket)
    authority = MoralisCuBudget(redis_client)

    outcome = authority.reserve(cost_cu)  # type: ignore[arg-type]

    assert outcome.allowed is False
    assert outcome.reason == "INVALID_CU_AMOUNT"
    assert list(redis_client.scan_iter(match="v2:provider:moralis:cu_usage:*")) == []


def test_legacy_can_spend_then_charge_pair_reserves_exactly_once(
    redis_socket: str,
) -> None:
    now = datetime(2026, 7, 31, 12, tzinfo=UTC)
    redis_client = _redis_client(redis_socket)
    authority = MoralisCuBudget(
        redis_client,
        monthly_limit=100,
        daily_hard_cap=100,
        daily_safety_bps=10_000,
        now_factory=lambda: now,
    )

    assert authority.can_spend(50) is True
    assert int(redis_client.get(DAY_KEY.format(day="2026-07-31")) or 0) == 50
    receipt = authority.charge(50, endpoint="legacy-test")
    assert receipt.allowed is True
    assert int(redis_client.get(DAY_KEY.format(day="2026-07-31")) or 0) == 50

    competing = MoralisCuBudget(
        redis_client,
        monthly_limit=100,
        daily_hard_cap=100,
        daily_safety_bps=10_000,
        now_factory=lambda: now,
    )
    assert competing.can_spend(60) is False
    assert int(redis_client.get(MONTH_KEY.format(month="2026-07")) or 0) == 50


def test_restart_rehydrates_reserved_spend_and_never_resets_budget(redis_socket: str) -> None:
    now = datetime(2026, 7, 19, 12, tzinfo=UTC)
    first = MoralisRateLimiter(
        redis_client=_redis_client(redis_socket),
        ledger_now_factory=lambda: now,
    )
    decision = first.allow_request(estimated_cu=50)
    assert decision.allowed is True

    restarted = MoralisRateLimiter(
        redis_client=_redis_client(redis_socket),
        ledger_now_factory=lambda: now,
    )
    status = restarted.as_dict()
    assert status["compute_budget"]["used_today"] == 50  # type: ignore[index]
    assert status["compute_budget"]["used_month"] == 50  # type: ignore[index]
    assert status["pending_reservation"] is None
    assert status["cu_ledger_available"] is True


def test_distributed_rps_guard_is_shared_across_limiter_instances(
    redis_socket: str,
) -> None:
    redis_client = _redis_client(redis_socket)
    limiters = [
        MoralisRateLimiter(redis_client=redis_client, rps=2)
        for _index in range(3)
    ]

    decisions = [limiter.allow_request(estimated_cu=1) for limiter in limiters]

    assert sum(decision.allowed for decision in decisions) == 2
    assert decisions[-1].reason == "DISTRIBUTED_RPS_CAP"
    assert limiters[-1].as_dict()["distributed_rps_guard"] is True
    assert limiters[-1].as_dict()["distributed_rps_guard_reason"] == "READY"


def test_stale_cu_health_never_bypasses_distributed_rps_guard(
    redis_socket: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limiter = MoralisRateLimiter(redis_client=_redis_client(redis_socket))
    assert limiter.cu is not None
    reserve = Mock(wraps=limiter.cu.reserve)
    monkeypatch.setattr(limiter.cu, "reserve", reserve)
    monkeypatch.setattr(
        limiter,
        "_consume_distributed_rps",
        lambda: "DISTRIBUTED_RPS_CAP",
    )
    limiter._ledger_health_reason = "DAILY_CU_BUDGET_EXHAUSTED"

    decision = limiter.allow_request(estimated_cu=10)

    assert decision.allowed is False
    assert decision.reason == "DISTRIBUTED_RPS_CAP"
    assert reserve.call_count == 0
    status = limiter.as_dict()
    assert status["self_imposed_rps_window_seconds"] == 1
    assert status["provider_documented_rps_window_seconds"] == 4


def test_reconcile_uses_original_period_keys_across_utc_midnight(redis_socket: str) -> None:
    clock = _MutableUtcClock(datetime(2026, 7, 31, 23, 59, 59, tzinfo=UTC))
    authority = MoralisCuBudget(
        _redis_client(redis_socket),
        monthly_limit=10_000,
        daily_hard_cap=1_000,
        daily_safety_bps=10_000,
        now_factory=clock,
    )
    reservation = authority.reserve(60)
    assert reservation.allowed is True

    clock.value = datetime(2026, 8, 1, 0, 0, 1, tzinfo=UTC)
    reconciled = authority.reconcile(reservation, actual_cu=40)
    assert reconciled.applied is True
    client = _redis_client(redis_socket)
    assert int(client.get(DAY_KEY.format(day="2026-07-31")) or 0) == 40
    assert int(client.get(MONTH_KEY.format(month="2026-07")) or 0) == 40
    assert client.get(DAY_KEY.format(day="2026-08-01")) is None
    assert client.get(MONTH_KEY.format(month="2026-08")) is None


def test_provider_actual_over_cap_is_recorded_then_future_reserves_stop(
    redis_socket: str,
) -> None:
    now = datetime(2026, 7, 31, 12, tzinfo=UTC)
    authority = MoralisCuBudget(
        _redis_client(redis_socket),
        monthly_limit=100,
        daily_hard_cap=100,
        daily_safety_bps=10_000,
        now_factory=lambda: now,
    )
    reservation = authority.reserve(50)
    assert reservation.allowed is True

    reconciliation = authority.reconcile(reservation, actual_cu=120)
    assert reconciliation.applied is True
    assert reconciliation.month_spent_cu == 120
    denied = authority.reserve(1)
    assert denied.allowed is False
    assert denied.reason == "MONTHLY_CU_BUDGET_EXHAUSTED"


@pytest.mark.parametrize(
    ("status_code", "headers", "expected_spend"),
    [
        (429, {"x-moralis-compute-units": "7"}, 7),
        (500, {}, 50),
        (403, {"x-moralis-compute-units": "0"}, 0),
    ],
)
def test_every_received_http_response_reconciles_provider_headers(
    redis_socket: str,
    status_code: int,
    headers: dict[str, str],
    expected_spend: int,
) -> None:
    now = datetime(2026, 7, 19, 12, tzinfo=UTC)
    redis_client = _redis_client(redis_socket)
    http_client = _StaticHttpClient(
        httpx.Response(status_code, headers=headers, json={"status": "provider response"})
    )
    limiter = MoralisRateLimiter(
        redis_client=redis_client,
        ledger_now_factory=lambda: now,
    )
    response = MoralisClient(
        api_key="fixture-key",  # noqa: S106 - non-secret test fixture
        limiter=limiter,
        http_client=http_client,  # type: ignore[arg-type]
    ).get(_token_transfers_spec(), token=VALID_TOKEN_ADDRESS)

    assert response.http_status == status_code
    assert response.error_class is None
    assert response.request_dispatched is True
    assert int(redis_client.get(DAY_KEY.format(day="2026-07-19")) or 0) == expected_spend
    assert int(redis_client.get(MONTH_KEY.format(month="2026-07")) or 0) == expected_spend


def test_timeout_retains_reservation_across_restart(redis_socket: str) -> None:
    now = datetime(2026, 7, 19, 12, tzinfo=UTC)
    redis_client = _redis_client(redis_socket)
    timeout = httpx.ReadTimeout("ambiguous delivery")
    http_client = _StaticHttpClient(timeout)
    limiter = MoralisRateLimiter(
        redis_client=redis_client,
        ledger_now_factory=lambda: now,
    )
    response = MoralisClient(
        api_key="fixture-key",  # noqa: S106 - non-secret test fixture
        limiter=limiter,
        http_client=http_client,  # type: ignore[arg-type]
    ).get(_token_transfers_spec(), token=VALID_TOKEN_ADDRESS)

    assert response.error_class == "ReadTimeout"
    assert response.request_dispatched is True
    assert int(redis_client.get(DAY_KEY.format(day="2026-07-19")) or 0) == 50
    restarted = MoralisRateLimiter(
        redis_client=_redis_client(redis_socket),
        ledger_now_factory=lambda: now,
    )
    assert restarted.as_dict()["compute_budget"]["used_today"] == 50  # type: ignore[index]


def test_refund_requires_proof_request_was_not_sent(redis_socket: str) -> None:
    now = datetime(2026, 7, 19, 12, tzinfo=UTC)
    redis_client = _redis_client(redis_socket)
    limiter = MoralisRateLimiter(
        redis_client=redis_client,
        ledger_now_factory=lambda: now,
    )
    assert limiter.allow_request(estimated_cu=50).allowed is True
    assert limiter.refund_pending() == 0
    assert int(redis_client.get(DAY_KEY.format(day="2026-07-19")) or 0) == 50
    assert limiter.refund_pending(request_was_not_sent=True) == 50
    assert int(redis_client.get(DAY_KEY.format(day="2026-07-19")) or 0) == 0


def test_lost_reconcile_reply_is_idempotently_retried_before_next_poll(
    redis_socket: str,
) -> None:
    now = datetime(2026, 7, 19, 12, tzinfo=UTC)
    durable_client = _redis_client(redis_socket)
    unreliable_client = _ApplyThenLoseReconcileReplyRedis(durable_client)
    limiter = MoralisRateLimiter(
        redis_client=unreliable_client,
        ledger_now_factory=lambda: now,
    )
    response = MoralisClient(
        api_key="fixture-key",  # noqa: S106 - non-secret test fixture
        limiter=limiter,
        http_client=_StaticHttpClient(
            httpx.Response(200, headers={"x-moralis-compute-units": "7"}, json={"ok": True})
        ),  # type: ignore[arg-type]
    ).get(_token_transfers_spec(), token=VALID_TOKEN_ADDRESS)

    assert response.payload is None
    assert response.error_class == "CU_LEDGER_UNAVAILABLE_RESERVATION_RETAINED"
    assert unreliable_client.reply_lost is True
    assert int(durable_client.get(DAY_KEY.format(day="2026-07-19")) or 0) == 7
    assert limiter.as_dict()["provider_polling_blocked"] is True

    # The retry sees the settled reservation record, succeeds idempotently, and
    # only then reserves the next request.  The -43 CU delta is not applied twice.
    next_decision = limiter.allow_request(estimated_cu=50)
    assert next_decision.allowed is True
    assert int(durable_client.get(DAY_KEY.format(day="2026-07-19")) or 0) == 57


def test_redis_outage_fails_optional_polling_closed_without_http_call() -> None:
    http_client = _StaticHttpClient(httpx.Response(200, json={"result": []}))
    limiter = MoralisRateLimiter(redis_client=_FailingRedis())
    client = MoralisClient(
        api_key="fixture-key",  # noqa: S106 - non-secret test fixture
        limiter=limiter,
        http_client=http_client,  # type: ignore[arg-type]
    )

    response = client.get(_token_transfers_spec(), token=VALID_TOKEN_ADDRESS)

    assert response.error_class == "RPS_LEDGER_UNAVAILABLE"
    assert response.request_dispatched is False
    assert http_client.calls == 0
    status = limiter.as_dict()
    assert status["cu_ledger_available"] is False
    assert status["provider_polling_blocked"] is True
    assert status["core_system_blocked"] is False


def test_default_client_without_durable_ledger_never_polls() -> None:
    http_client = _StaticHttpClient(httpx.Response(200, json={"result": []}))
    response = MoralisClient(
        api_key="fixture-key",  # noqa: S106 - non-secret test fixture
        http_client=http_client,  # type: ignore[arg-type]
    ).get(_token_transfers_spec(), token=VALID_TOKEN_ADDRESS)

    assert response.error_class == "CU_LEDGER_REQUIRED"
    assert response.request_dispatched is False
    assert http_client.calls == 0
