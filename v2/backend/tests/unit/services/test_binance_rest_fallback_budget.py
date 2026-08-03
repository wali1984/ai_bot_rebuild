from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import redis

from v2.backend.app.services import binance_unified_websocket_transport as policy


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
            client = redis.Redis(unix_socket_path=socket_path, decode_responses=True)
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


def _bind_shared_budget(
    monkeypatch: pytest.MonkeyPatch,
    *,
    socket_path: str,
    budget: int,
) -> tuple[redis.Redis, str]:
    client = redis.Redis(unix_socket_path=socket_path, decode_responses=True)
    prefix = "test:v2:binance:rest_fallback:budget:"
    minute = 30_000_000
    monkeypatch.setattr(policy, "_REST_BUDGET_REDIS_CLIENT", client)
    monkeypatch.setattr(policy, "_REST_BUDGET_REDIS_TRIED", True)
    monkeypatch.setattr(policy, "REST_FALLBACK_BUDGET_REDIS_KEY_PREFIX", prefix)
    monkeypatch.setattr(policy, "time", SimpleNamespace(time=lambda: minute * 60.0))
    monkeypatch.setenv(policy.REST_FALLBACK_BUDGET_PER_MINUTE_ENV, str(budget))
    return client, f"{prefix}{minute}"


def test_shared_budget_reserve_is_atomic_and_never_charges_denials(
    redis_socket: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, key = _bind_shared_budget(monkeypatch, socket_path=redis_socket, budget=10)

    def reserve() -> tuple[bool, dict[str, object]]:
        allowed, _reason, diagnostics = policy._rest_fallback_budget_check(
            request_weight=2,
            require_shared_budget=True,
        )
        return allowed, diagnostics

    with ThreadPoolExecutor(max_workers=20) as pool:
        outcomes = list(pool.map(lambda _index: reserve(), range(40)))

    assert sum(allowed for allowed, _diagnostics in outcomes) == 5
    assert int(cast(Any, client.get(key)) or 0) == 10
    key_ttl_ms = int(cast(Any, client.pttl(key)))
    assert 0 < key_ttl_ms <= 120_000
    denied = [diagnostics for allowed, diagnostics in outcomes if not allowed]
    assert denied
    assert all(diagnostics["budget_used_this_minute"] == 10 for diagnostics in denied)
    assert all(diagnostics["budget_attempted_this_minute"] == 12 for diagnostics in denied)


def test_repeated_denials_leave_shared_counter_at_admitted_weight(
    redis_socket: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, key = _bind_shared_budget(monkeypatch, socket_path=redis_socket, budget=10)
    client.set(key, "10", px=120_000)

    outcomes = [
        policy._rest_fallback_budget_check(
            request_weight=1,
            require_shared_budget=True,
        )
        for _index in range(100)
    ]

    assert all(allowed is False for allowed, _reason, _diagnostics in outcomes)
    assert int(cast(Any, client.get(key)) or 0) == 10
    assert {
        reason.split(":", 1)[0] if reason else None for _allowed, reason, _diagnostics in outcomes
    } == {"REST_FALLBACK_BUDGET_EXHAUSTED_BAN_PROTECTION"}


@pytest.mark.parametrize(
    ("value", "ttl_seconds", "expected_reason"),
    [
        ("5", None, "REST_FALLBACK_BUDGET_PERSISTENT_KEY_FAIL_CLOSED"),
        ("not-an-integer", 120, "REST_FALLBACK_BUDGET_STATE_INVALID_FAIL_CLOSED"),
    ],
)
def test_invalid_shared_budget_state_fails_closed_without_mutation(
    redis_socket: str,
    monkeypatch: pytest.MonkeyPatch,
    value: str,
    ttl_seconds: int | None,
    expected_reason: str,
) -> None:
    client, key = _bind_shared_budget(monkeypatch, socket_path=redis_socket, budget=10)
    if ttl_seconds is None:
        client.set(key, value)
    else:
        client.set(key, value, ex=ttl_seconds)

    allowed, reason, _diagnostics = policy._rest_fallback_budget_check(
        request_weight=1,
        require_shared_budget=True,
    )

    assert allowed is False
    assert reason == expected_reason
    assert client.get(key) == value


def test_process_local_denials_do_not_consume_phantom_weight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    minute = 30_000_000
    monkeypatch.setattr(policy, "_REST_BUDGET_REDIS_CLIENT", None)
    monkeypatch.setattr(policy, "_REST_BUDGET_REDIS_TRIED", True)
    monkeypatch.setattr(policy, "time", SimpleNamespace(time=lambda: minute * 60.0))
    monkeypatch.setattr(policy, "_REST_BUDGET_LOCAL_WINDOW", {"minute": minute, "count": 2})
    monkeypatch.setenv(policy.REST_FALLBACK_BUDGET_PER_MINUTE_ENV, "3")

    allowed, reason, diagnostics = policy._rest_fallback_budget_check(request_weight=2)

    assert allowed is False
    assert reason == "REST_FALLBACK_BUDGET_EXHAUSTED_BAN_PROTECTION:4>3_per_minute_local"
    assert diagnostics["budget_used_this_minute"] == 2
    assert diagnostics["budget_attempted_this_minute"] == 4
    assert policy._REST_BUDGET_LOCAL_WINDOW["count"] == 2
