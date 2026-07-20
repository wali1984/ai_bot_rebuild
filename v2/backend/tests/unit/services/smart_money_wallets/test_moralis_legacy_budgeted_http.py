from __future__ import annotations

import json
import shutil
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import redis

from v2.backend.app.cli import v2_moralis_wallet_watchlist_bootstrap as bootstrap
from v2.backend.app.services.smart_money_wallets.budgeted_http import (
    budgeted_moralis_get_json,
)
from v2.backend.app.services.smart_money_wallets.cu_budget import MoralisCuBudget
from v2.backend.app.services.smart_money_wallets.poller import poll_token_transfers
from v2.backend.app.services.smart_money_wallets.rate_limit import MoralisRateLimiter


class _QueueHttpClient:
    def __init__(
        self,
        responses: list[httpx.Response | Exception],
        redis_client: redis.Redis,
    ) -> None:
        self.responses = list(responses)
        self.redis_client = redis_client
        self.urls: list[str] = []
        self.params: list[dict[str, object]] = []
        self.spent_at_dispatch: list[int] = []

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, object],
    ) -> httpx.Response:
        assert headers["X-API-Key"]
        self.urls.append(url)
        self.params.append(params)
        self.spent_at_dispatch.append(MoralisCuBudget(self.redis_client).day_spent())
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _FailingRedis:
    def get(self, *_args: Any, **_kwargs: Any) -> Any:
        raise ConnectionError("redis unavailable")

    def eval(self, *_args: Any, **_kwargs: Any) -> Any:
        raise ConnectionError("redis unavailable")

    def set(self, *_args: Any, **_kwargs: Any) -> Any:
        raise ConnectionError("redis unavailable")


@pytest.fixture()
def redis_client(tmp_path: Path) -> Iterator[redis.Redis]:
    executable = shutil.which("redis-server")
    if executable is None:
        pytest.skip("redis-server is required for the durable Moralis transport test")
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
    client = redis.Redis(unix_socket_path=socket_path, decode_responses=True)
    while time.monotonic() < deadline:
        try:
            if client.ping():
                break
        except (OSError, redis.RedisError):
            time.sleep(0.02)
    else:
        process.terminate()
        process.wait(timeout=5)
        pytest.fail("ephemeral redis-server did not become ready")
    client.flushdb()
    try:
        yield client
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_received_error_status_reconciles_header_after_pre_reservation(
    redis_client: redis.Redis,
) -> None:
    http_client = _QueueHttpClient(
        [
            httpx.Response(
                429,
                headers={"x-moralis-compute-units": "7"},
                json={"message": "rate limited"},
            )
        ],
        redis_client,
    )

    outcome = budgeted_moralis_get_json(
        api_key="fixture-key",  # noqa: S106 - non-secret test fixture
        endpoint_id="token_address_transfers",
        path="/erc20/0xtoken/transfers",
        estimated_cu=50,
        limiter=MoralisRateLimiter(redis_client=redis_client),
        http_client=http_client,
    )

    assert outcome.http_status == 429
    assert outcome.accounted_cu == 7
    assert outcome.reconciliation_applied is True
    assert http_client.spent_at_dispatch == [50]
    assert MoralisCuBudget(redis_client).day_spent() == 7


def test_timeout_retains_conservative_estimate(redis_client: redis.Redis) -> None:
    http_client = _QueueHttpClient(
        [httpx.ReadTimeout("ambiguous delivery")],
        redis_client,
    )

    outcome = budgeted_moralis_get_json(
        api_key="fixture-key",  # noqa: S106 - non-secret test fixture
        endpoint_id="token_holders",
        path="/erc20/0xtoken/owners",
        estimated_cu=100,
        limiter=MoralisRateLimiter(redis_client=redis_client),
        http_client=http_client,
    )

    assert outcome.http_status is None
    assert outcome.error_class == "ReadTimeout"
    assert outcome.request_dispatched is True
    assert outcome.accounted_cu == 100
    assert http_client.spent_at_dispatch == [100]
    assert MoralisCuBudget(redis_client).day_spent() == 100


def test_ledger_outage_blocks_before_http_dispatch() -> None:
    failing_redis = _FailingRedis()
    http_client = _QueueHttpClient(  # type: ignore[arg-type]
        [httpx.Response(200, json={"result": []})],
        failing_redis,
    )

    outcome = budgeted_moralis_get_json(
        api_key="fixture-key",  # noqa: S106 - non-secret test fixture
        endpoint_id="token_holders",
        path="/erc20/0xtoken/owners",
        estimated_cu=100,
        limiter=MoralisRateLimiter(redis_client=failing_redis),
        http_client=http_client,
    )

    assert outcome.error_class == "CU_LEDGER_UNAVAILABLE"
    assert outcome.request_dispatched is False
    assert http_client.urls == []


def test_poller_budgets_weight_lookup_and_transfer_independently(
    redis_client: redis.Redis,
) -> None:
    http_client = _QueueHttpClient(
        [
            httpx.Response(
                200,
                headers={"x-moralis-compute-units": "3"},
                json=[
                    {
                        "endpoint": "getTokenAddressTransfers",
                        "rateLimitCost": 50,
                    }
                ],
            ),
            httpx.Response(
                429,
                headers={"x-moralis-compute-units": "7"},
                json={"message": "rate limited"},
            ),
        ],
        redis_client,
    )

    report = poll_token_transfers(
        redis_client,
        "fixture-key",  # noqa: S106 - non-secret test fixture
        watchlist={"LINKUSDT": "0xtoken"},
        http_client=http_client,
    )

    assert http_client.urls == [
        "https://deep-index.moralis.io/api/v2.2/info/endpointWeights",
        "https://deep-index.moralis.io/api/v2.2/erc20/0xtoken/transfers",
    ]
    assert http_client.spent_at_dispatch == [50, 53]
    assert report["results"][0]["http_status"] == 429
    assert report["budget"]["cu_spent_this_poll"] == 10
    assert MoralisCuBudget(redis_client).day_spent() == 10


def test_wallet_bootstrap_reserves_each_endpoint_and_keeps_timeout_charge(
    redis_client: redis.Redis,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seed_path = tmp_path / "wallet_watchlist_seed.yaml"
    seed_path.write_text(json.dumps({"wallets": []}), encoding="utf-8")
    monkeypatch.setattr(bootstrap, "SEED_PATH", seed_path)
    monkeypatch.setattr(
        bootstrap,
        "_pollable_tokens",
        lambda _redis: [
            {
                "symbol": "LINKUSDT",
                "chain": "ethereum",
                "contract_address": "0xtoken",
            }
        ],
    )
    http_client = _QueueHttpClient(
        [
            httpx.Response(
                200,
                headers={"x-moralis-compute-units": "11"},
                json={"result": []},
            ),
            httpx.ReadTimeout("ambiguous transfer delivery"),
        ],
        redis_client,
    )

    report = bootstrap.bootstrap_watchlist(
        redis_client,
        api_key="fixture-key",  # noqa: S106 - non-secret test fixture
        http_client=http_client,
    )

    assert http_client.spent_at_dispatch == [50, 61]
    assert [params["limit"] for params in http_client.params] == [20, 50]
    assert report["tokens_polled"] == 1
    assert report["cu_spent"] == 61
    assert MoralisCuBudget(redis_client).day_spent() == 61
    assert report["no_wallet_labeled_verified_smart_money"] is True
