from __future__ import annotations

import json
import shutil
import subprocess
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import redis

from v2.backend.app.cli import v2_moralis_provider_loop as provider_loop
from v2.backend.app.cli import v2_moralis_wallet_watchlist_bootstrap as bootstrap
from v2.backend.app.services.smart_money_wallets.budgeted_http import (
    budgeted_moralis_get_json,
)
from v2.backend.app.services.smart_money_wallets.cu_budget import MoralisCuBudget
from v2.backend.app.services.smart_money_wallets.endpoint_registry import (
    MORALIS_SCHEDULER_STATUS_KEY,
)
from v2.backend.app.services.smart_money_wallets.poller import poll_token_transfers
from v2.backend.app.services.smart_money_wallets.rate_limit import MoralisRateLimiter

VALID_TOKEN_ADDRESS = "0x" + ("1" * 40)
VALID_WALLET_ADDRESS = "0x" + ("2" * 40)


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

    assert outcome.error_class == "RPS_LEDGER_UNAVAILABLE"
    assert outcome.request_dispatched is False
    assert http_client.urls == []


def test_scheduler_lease_and_cadence_claims_are_durable_in_real_redis(
    redis_client: redis.Redis,
) -> None:
    lease_token, lease_available, acquired = provider_loop._acquire_scheduler_lease(
        redis_client,
        chain="eth",
    )
    assert lease_available is True
    assert acquired is True
    assert lease_token is not None
    _other_token, other_available, other_acquired = (
        provider_loop._acquire_scheduler_lease(redis_client, chain="eth")
    )
    assert other_available is True
    assert other_acquired is False
    assert provider_loop._renew_scheduler_lease(
        redis_client,
        chain="eth",
        lease_token=lease_token,
    ) is True

    claimed, state_available, claim_key, claim_value = provider_loop._claim_poll_job(
        redis_client,
        chain="eth",
        job_id="fixture-job",
        cadence_seconds=600,
        lease_token=lease_token,
    )
    assert (claimed, state_available) == (True, True)
    denied, state_available, _key, _value = provider_loop._claim_poll_job(
        redis_client,
        chain="eth",
        job_id="fixture-job",
        cadence_seconds=600,
        lease_token=lease_token,
    )
    assert (denied, state_available) == (False, True)
    assert claim_key is not None
    assert claim_value is not None
    assert provider_loop._release_cadence_claim(
        redis_client,
        key=claim_key,
        value=claim_value,
    ) is True
    with ThreadPoolExecutor(max_workers=8) as pool:
        concurrent = list(
            pool.map(
                lambda _index: provider_loop._claim_poll_job(
                    redis_client,
                    chain="eth",
                    job_id="concurrent-fixture-job",
                    cadence_seconds=600,
                    lease_token=lease_token,
                ),
                range(16),
            )
        )
    assert sum(result[0] for result in concurrent) == 1
    redis_client.set(provider_loop._scheduler_lease_key("eth"), "replacement-worker")
    stale_claim = provider_loop._claim_poll_job(
        redis_client,
        chain="eth",
        job_id="stale-worker-job",
        cadence_seconds=600,
        lease_token=lease_token,
    )
    assert stale_claim[:2] == (False, False)
    assert provider_loop._write_rotation_cursor(
        redis_client,
        chain="eth",
        job_id="stale-worker-job",
        lease_token=lease_token,
    ) is False
    redis_client.set(provider_loop._scheduler_lease_key("eth"), lease_token)
    assert provider_loop._release_scheduler_lease(
        redis_client,
        chain="eth",
        lease_token=lease_token,
    ) is True


def test_legacy_poller_is_retired_without_http_cu_or_identity_publication(
    redis_client: redis.Redis,
) -> None:
    http_client = _QueueHttpClient([], redis_client)

    report = poll_token_transfers(
        redis_client,
        "fixture-key",  # noqa: S106 - non-secret test fixture
        watchlist={"../../unsafe": "0x/../unsafe?key=value"},
        http_client=http_client,
    )

    assert http_client.urls == []
    assert report["results"] == []
    assert report["request_count"] == 0
    assert report["legacy_transport_retired"] is True
    assert report["budget"]["cu_spent_this_poll"] == 0
    assert report["budget"]["poll_suppressed_reason"] == (
        "LEGACY_TRANSPORT_RETIRED_CANONICAL_ONLY"
    )
    assert MoralisCuBudget(redis_client).day_spent() == 0
    assert all("unsafe" not in str(key) for key in redis_client.scan_iter("*"))


def test_legacy_poller_defers_without_http_or_cu_when_canonical_provider_owns_transport(
    redis_client: redis.Redis,
) -> None:
    redis_client.set(
        MORALIS_SCHEDULER_STATUS_KEY,
        json.dumps(
            {
                "provider": "moralis",
                "canonical_token_transfer_transport_owner": True,
            }
        ),
        ex=300,
    )
    http_client = _QueueHttpClient([], redis_client)

    report = poll_token_transfers(
        redis_client,
        "fixture-key",  # noqa: S106 - non-secret test fixture
        watchlist={"LINKUSDT": "0xtoken"},
        http_client=http_client,
    )

    assert http_client.urls == []
    assert MoralisCuBudget(redis_client).day_spent() == 0
    assert report["request_count"] == 0
    assert report["canonical_provider_transport_owner"] is True
    assert report["legacy_transport_retired"] is True
    assert report["budget"]["poll_suppressed_reason"] == (
        "LEGACY_TRANSPORT_RETIRED_CANONICAL_ONLY"
    )


def test_wallet_bootstrap_budgets_holders_and_never_duplicates_token_transfers(
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
                "contract_address": VALID_TOKEN_ADDRESS,
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
        ],
        redis_client,
    )
    now = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    redis_client.set(
        f"v2:moralis:token_holders:eth:{VALID_TOKEN_ADDRESS}",
        json.dumps(
            {
                "schema_version": "moralis_normalized_payload_v1",
                "provider": "moralis",
                "endpoint_id": "token_holders",
                "feature_family": "token_holders",
                "symbol": "LINKUSDT",
                "chain": "eth",
                "wallet": None,
                "token": VALID_TOKEN_ADDRESS,
                "event_time": None,
                "feature_cutoff": None,
                "available_at": now,
                "ingested_at": now,
                "generated_at": now,
                "ttl_seconds": 86_400,
                "provider_ready": True,
                "actual_payload_present": True,
                "subscription_status": "READY",
                "auth_status": "READY",
                "canonical_records": [
                    {
                        "owner_address": VALID_WALLET_ADDRESS,
                        "owner_address_label": None,
                        "is_contract": False,
                        "usd_value": "1234.5",
                    }
                ],
            }
        ),
        ex=86_400,
    )

    report = bootstrap.bootstrap_watchlist(
        redis_client,
        api_key="fixture-key",  # noqa: S106 - non-secret test fixture
        http_client=http_client,
    )

    assert http_client.spent_at_dispatch == []
    assert http_client.params == []
    assert report["tokens_polled"] == 1
    assert report["canonical_holder_cache_hit_count"] == 1
    assert report["holder_http_request_count"] == 0
    assert report["cu_spent"] == 0
    assert report["token_transfer_request_count"] == 0
    assert report["token_transfer_transport_owner"] == (
        "CANONICAL_PROVIDER_SCHEDULER"  # noqa: S105 - ownership label, not a secret
    )
    assert all("/transfers" not in url for url in http_client.urls)
    assert MoralisCuBudget(redis_client).day_spent() == 0
    assert report["no_wallet_labeled_verified_smart_money"] is True


def test_wallet_bootstrap_keeps_same_address_on_different_chains_distinct(
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
                "chain": "eth",
                "contract_address": "0x" + ("1" * 40),
            },
            {
                "symbol": "BNXUSDT",
                "chain": "bsc",
                "contract_address": "0x" + ("3" * 40),
            },
        ],
    )
    monkeypatch.setattr(
        bootstrap,
        "read_canonical_records",
        lambda *_args, **_kwargs: SimpleNamespace(
            ready=True,
            reason="READY",
            records=(
                {
                    "owner_address": VALID_WALLET_ADDRESS,
                    "owner_address_label": None,
                    "is_contract": False,
                    "usd_value": "1000",
                },
            ),
        ),
    )

    report = bootstrap.bootstrap_watchlist(redis_client)
    seed = json.loads(seed_path.read_text(encoding="utf-8"))

    assert report["t0_count"] == 2
    assert len(seed["wallets"]) == 2
    assert {(row["chain"], row["address"]) for row in seed["wallets"]} == {
        ("eth", VALID_WALLET_ADDRESS),
        ("bsc", VALID_WALLET_ADDRESS),
    }


def test_wallet_bootstrap_quarantines_identity_before_cu_http_or_seed_publication(
    redis_client: redis.Redis,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seed_path = tmp_path / "wallet_watchlist_seed.yaml"
    seed_path.write_text(json.dumps({"wallets": []}), encoding="utf-8")
    monkeypatch.setattr(bootstrap, "SEED_PATH", seed_path)
    malicious_contract = "0x/../unsafe?api_key=leak"
    monkeypatch.setattr(
        bootstrap,
        "_pollable_tokens",
        lambda _redis: [
            {
                "symbol": "../../UNSAFE",
                "chain": "ethereum",
                "contract_address": malicious_contract,
            }
        ],
    )
    http_client = _QueueHttpClient([], redis_client)

    report = bootstrap.bootstrap_watchlist(
        redis_client,
        api_key="fixture-key",  # noqa: S106 - non-secret test fixture
        http_client=http_client,
    )

    assert http_client.urls == []
    assert MoralisCuBudget(redis_client).day_spent() == 0
    assert report["tokens_polled"] == 0
    assert report["quarantined_token_count"] == 1
    assert report["quarantined_tokens"][0]["reason"] == "TOKEN_ADDRESS_INVALID"
    assert malicious_contract not in seed_path.read_text(encoding="utf-8")
    assert all("unsafe" not in str(key).lower() for key in redis_client.scan_iter("*"))
