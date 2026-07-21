from __future__ import annotations

import json
import shutil
import subprocess
import time
import uuid
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


def _empty_candidate_watchlist_seed() -> dict[str, Any]:
    return {
        "schema_version": "moralis_wallet_watchlist_seed_v1",
        "policy": {
            "empty_watchlist_status": "CONFIGURED_NO_WATCHLIST",
            "t0_max_wallets": 50,
            "t1_max_wallets": 250,
            "unknown_wallet_is_smart_money": False,
        },
        "wallets": [],
    }


def _assert_redis_epoch_within_inclusive_bounds(
    *,
    created_at_epoch: int,
    before_epoch: int,
    after_epoch: int,
) -> None:
    assert before_epoch <= after_epoch
    assert before_epoch <= created_at_epoch <= after_epoch


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
        rotation_universe_digest="0" * 64,
        lease_token=lease_token,
    ) is False
    redis_client.set(provider_loop._scheduler_lease_key("eth"), lease_token)
    assert provider_loop._release_scheduler_lease(
        redis_client,
        chain="eth",
        lease_token=lease_token,
    ) is True


def test_real_redis_earned_credit_carries_releases_and_rejects_stale_reset(
    redis_client: redis.Redis,
) -> None:
    lease_token, state_available, acquired = provider_loop._acquire_scheduler_lease(
        redis_client,
        chain="eth",
    )
    assert state_available is True
    assert acquired is True
    assert lease_token is not None
    now_seconds = int(redis_client.time()[0])
    state_key = provider_loop.PACED_CU_ADMISSION_WINDOW_PREFIX
    claim_kwargs = {
        "chain": "eth",
        "lease_token": lease_token,
        "scheduler_interval_seconds": 300,
        "remaining_today_cu": 26_130,
        "remaining_month_cu": 1_945_510,
        "daily_admission_opportunities": 158,
        "monthly_admission_opportunities": 3_038,
        "utc_day_reset_epoch_seconds": now_seconds + 86_400,
        "utc_month_reset_epoch_seconds": now_seconds + 2_592_000,
    }

    first = provider_loop._claim_paced_compute_units(
        redis_client,
        cost_cu=250,
        **claim_kwargs,
    )
    assert first[0] is False
    assert first[1] is True
    assert first[2] == pytest.approx(26_130 / 158, rel=1e-6)

    stored_window = int(redis_client.hget(state_key, "window_id"))
    redis_client.hset(state_key, "window_id", stored_window - 1)
    second = provider_loop._claim_paced_compute_units(
        redis_client,
        cost_cu=250,
        **claim_kwargs,
    )
    assert second[0] is True
    assert second[1] is True
    assert second[2] == pytest.approx((2 * (26_130 / 158)) - 250, rel=1e-5)

    assert provider_loop._release_paced_compute_units(
        redis_client,
        chain="eth",
        lease_token=lease_token,
        window_id=second[3],
        cost_cu=250,
        reservation_id=second[4],
    ) is True
    assert float(redis_client.hget(state_key, "credit_cu")) == pytest.approx(
        2 * (26_130 / 158),
        rel=1e-5,
    )

    state_before = redis_client.hgetall(state_key)
    stale = provider_loop._claim_paced_compute_units(
        redis_client,
        chain="eth",
        lease_token=lease_token,
        scheduler_interval_seconds=300,
        cost_cu=10,
        remaining_today_cu=26_130,
        remaining_month_cu=1_945_510,
        daily_admission_opportunities=158,
        monthly_admission_opportunities=3_038,
        utc_day_reset_epoch_seconds=now_seconds,
        utc_month_reset_epoch_seconds=now_seconds + 2_592_000,
    )
    assert stale[0] is False
    assert stale[1] is False
    assert redis_client.hgetall(state_key) == state_before


def test_real_redis_paced_release_is_exact_once_and_field_bound(
    redis_client: redis.Redis,
) -> None:
    lease_token, state_available, acquired = provider_loop._acquire_scheduler_lease(
        redis_client,
        chain="eth",
    )
    assert state_available is True
    assert acquired is True
    assert lease_token is not None
    now_seconds = int(redis_client.time()[0])
    day_reset = now_seconds + 86_400
    month_reset = now_seconds + 2_592_000
    admitted, available, credit, window_id, reservation_id = (
        provider_loop._claim_paced_compute_units(
            redis_client,
            chain="eth",
            lease_token=lease_token,
            scheduler_interval_seconds=300,
            cost_cu=50,
            remaining_today_cu=100,
            remaining_month_cu=100,
            daily_admission_opportunities=1,
            monthly_admission_opportunities=1,
            utc_day_reset_epoch_seconds=day_reset,
            utc_month_reset_epoch_seconds=month_reset,
        )
    )

    assert admitted is True
    assert available is True
    assert credit == pytest.approx(50.0)
    assert window_id is not None
    assert reservation_id is not None
    reservation_key = provider_loop._paced_cu_reservation_key(reservation_id)
    credit_key = provider_loop.PACED_CU_ADMISSION_WINDOW_PREFIX
    reservation = redis_client.hgetall(reservation_key)
    created_at_epoch = int(reservation.pop("created_at_epoch"))
    after_claim_seconds = int(redis_client.time()[0])
    _assert_redis_epoch_within_inclusive_bounds(
        created_at_epoch=created_at_epoch,
        before_epoch=now_seconds,
        after_epoch=after_claim_seconds,
    )
    assert reservation == {
        "reservation_id": reservation_id,
        "lease_key": provider_loop._scheduler_lease_key("eth"),
        "lease_token": lease_token,
        "window_id": str(window_id),
        "cost_cu": "50",
        "credit_key": credit_key,
        "day_reset_epoch": str(day_reset),
        "month_reset_epoch": str(month_reset),
    }
    expected_expires_at = min(day_reset, month_reset) + (2 * 300)
    assert redis_client.expiretime(reservation_key) == expected_expires_at
    assert 0 < redis_client.ttl(reservation_key) <= 87_000

    def release(
        *,
        token: str = lease_token,
        release_window: int = window_id,
        cost: int = 50,
        receipt: str = reservation_id,
    ) -> bool:
        return provider_loop._release_paced_compute_units(
            redis_client,
            chain="eth",
            lease_token=token,
            window_id=release_window,
            cost_cu=cost,
            reservation_id=receipt,
        )

    assert release(receipt=uuid.uuid4().hex) is False
    assert release(cost=49) is False
    assert release(release_window=window_id + 1) is False
    assert float(redis_client.hget(credit_key, "credit_cu")) == pytest.approx(50.0)
    assert redis_client.exists(reservation_key) == 1

    replacement_token = uuid.uuid4().hex
    redis_client.set(provider_loop._scheduler_lease_key("eth"), replacement_token)
    assert release(token=replacement_token) is False
    assert release() is False
    redis_client.set(provider_loop._scheduler_lease_key("eth"), lease_token)

    redis_client.hset(credit_key, "day_reset_epoch", day_reset + 1)
    assert release() is False
    redis_client.hset(credit_key, "day_reset_epoch", day_reset)

    redis_client.hdel(credit_key, "credit_cu")
    assert release() is False
    redis_client.hset(credit_key, "credit_cu", 50)

    assert release() is True
    assert float(redis_client.hget(credit_key, "credit_cu")) == pytest.approx(100.0)
    assert redis_client.exists(reservation_key) == 0
    assert release() is False
    assert float(redis_client.hget(credit_key, "credit_cu")) == pytest.approx(100.0)
    assert provider_loop._finalize_paced_compute_units(
        redis_client,
        chain="eth",
        lease_token=lease_token,
        window_id=window_id,
        cost_cu=50,
        reservation_id=reservation_id,
    ) is False


def test_reservation_created_at_bound_accepts_redis_second_straddle() -> None:
    _assert_redis_epoch_within_inclusive_bounds(
        created_at_epoch=1_000_001,
        before_epoch=1_000_000,
        after_epoch=1_000_001,
    )
    _assert_redis_epoch_within_inclusive_bounds(
        created_at_epoch=1_000_000,
        before_epoch=1_000_000,
        after_epoch=1_000_001,
    )


def test_real_redis_concurrent_paced_release_refunds_exactly_once(
    redis_client: redis.Redis,
) -> None:
    lease_token, state_available, acquired = provider_loop._acquire_scheduler_lease(
        redis_client,
        chain="eth",
    )
    assert state_available is True
    assert acquired is True
    assert lease_token is not None
    now_seconds = int(redis_client.time()[0])
    claim = provider_loop._claim_paced_compute_units(
        redis_client,
        chain="eth",
        lease_token=lease_token,
        scheduler_interval_seconds=300,
        cost_cu=50,
        remaining_today_cu=100,
        remaining_month_cu=100,
        daily_admission_opportunities=1,
        monthly_admission_opportunities=1,
        utc_day_reset_epoch_seconds=now_seconds + 86_400,
        utc_month_reset_epoch_seconds=now_seconds + 2_592_000,
    )
    assert claim[0] is True
    assert claim[3] is not None
    assert claim[4] is not None

    def release(_index: int) -> bool:
        return provider_loop._release_paced_compute_units(
            redis_client,
            chain="eth",
            lease_token=lease_token,
            window_id=claim[3],
            cost_cu=50,
            reservation_id=claim[4],
        )

    with ThreadPoolExecutor(max_workers=16) as pool:
        release_results = list(pool.map(release, range(32)))

    assert sum(release_results) == 1
    assert float(
        redis_client.hget(
            provider_loop.PACED_CU_ADMISSION_WINDOW_PREFIX,
            "credit_cu",
        )
    ) == pytest.approx(100.0)
    assert redis_client.exists(
        provider_loop._paced_cu_reservation_key(claim[4])
    ) == 0


def test_real_redis_finalize_and_worker_restart_keep_ambiguous_claim_charged(
    redis_client: redis.Redis,
) -> None:
    old_lease, state_available, acquired = provider_loop._acquire_scheduler_lease(
        redis_client,
        chain="eth",
    )
    assert state_available is True
    assert acquired is True
    assert old_lease is not None
    now_seconds = int(redis_client.time()[0])
    claim_kwargs = {
        "chain": "eth",
        "lease_token": old_lease,
        "scheduler_interval_seconds": 300,
        "cost_cu": 50,
        "remaining_today_cu": 100,
        "remaining_month_cu": 100,
        "daily_admission_opportunities": 1,
        "monthly_admission_opportunities": 1,
        "utc_day_reset_epoch_seconds": now_seconds + 86_400,
        "utc_month_reset_epoch_seconds": now_seconds + 2_592_000,
    }
    dispatched_claim = provider_loop._claim_paced_compute_units(
        redis_client,
        **claim_kwargs,
    )
    assert dispatched_claim[0] is True
    assert provider_loop._finalize_paced_compute_units(
        redis_client,
        chain="eth",
        lease_token=old_lease,
        window_id=dispatched_claim[3],
        cost_cu=50,
        reservation_id=dispatched_claim[4],
    ) is True
    assert provider_loop._finalize_paced_compute_units(
        redis_client,
        chain="eth",
        lease_token=old_lease,
        window_id=dispatched_claim[3],
        cost_cu=50,
        reservation_id=dispatched_claim[4],
    ) is False
    assert provider_loop._release_paced_compute_units(
        redis_client,
        chain="eth",
        lease_token=old_lease,
        window_id=dispatched_claim[3],
        cost_cu=50,
        reservation_id=dispatched_claim[4],
    ) is False

    ambiguous_claim = provider_loop._claim_paced_compute_units(
        redis_client,
        **claim_kwargs,
    )
    assert ambiguous_claim[0] is True
    assert ambiguous_claim[4] is not None
    reservation_key = provider_loop._paced_cu_reservation_key(ambiguous_claim[4])
    credit_key = provider_loop.PACED_CU_ADMISSION_WINDOW_PREFIX
    assert float(redis_client.hget(credit_key, "credit_cu")) == pytest.approx(0.0)
    assert redis_client.ttl(reservation_key) > 0

    assert provider_loop._release_scheduler_lease(
        redis_client,
        chain="eth",
        lease_token=old_lease,
    ) is True
    new_lease, new_state_available, new_acquired = (
        provider_loop._acquire_scheduler_lease(redis_client, chain="eth")
    )
    assert new_state_available is True
    assert new_acquired is True
    assert new_lease is not None
    assert new_lease != old_lease
    assert provider_loop._release_paced_compute_units(
        redis_client,
        chain="eth",
        lease_token=new_lease,
        window_id=ambiguous_claim[3],
        cost_cu=50,
        reservation_id=ambiguous_claim[4],
    ) is False
    assert provider_loop._release_paced_compute_units(
        redis_client,
        chain="eth",
        lease_token=old_lease,
        window_id=ambiguous_claim[3],
        cost_cu=50,
        reservation_id=ambiguous_claim[4],
    ) is False
    assert float(redis_client.hget(credit_key, "credit_cu")) == pytest.approx(0.0)
    assert redis_client.exists(reservation_key) == 1

    redis_client.delete(reservation_key)
    assert redis_client.exists(reservation_key) == 0
    assert float(redis_client.hget(credit_key, "credit_cu")) == pytest.approx(0.0)


def test_real_redis_cross_chain_claims_share_one_atomic_credit_authority(
    redis_client: redis.Redis,
) -> None:
    leases: dict[str, str] = {}
    for chain in ("eth", "arbitrum"):
        lease_token, state_available, acquired = (
            provider_loop._acquire_scheduler_lease(redis_client, chain=chain)
        )
        assert state_available is True
        assert acquired is True
        assert lease_token is not None
        leases[chain] = lease_token
    now_seconds = int(redis_client.time()[0])

    def claim(chain: str) -> tuple[str, tuple[bool, bool, float, int | None, str | None]]:
        result = provider_loop._claim_paced_compute_units(
            redis_client,
            chain=chain,
            lease_token=leases[chain],
            scheduler_interval_seconds=300,
            cost_cu=100,
            remaining_today_cu=100,
            remaining_month_cu=100,
            daily_admission_opportunities=1,
            monthly_admission_opportunities=1,
            utc_day_reset_epoch_seconds=now_seconds + 86_400,
            utc_month_reset_epoch_seconds=now_seconds + 2_592_000,
        )
        return chain, result

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = dict(pool.map(claim, ("eth", "arbitrum")))

    admitted_chains = [chain for chain, result in results.items() if result[0]]
    assert len(admitted_chains) == 1
    assert all(result[1] is True for result in results.values())
    assert len(
        list(
            redis_client.scan_iter(
                f"{provider_loop.PACED_CU_RESERVATION_KEY_PREFIX}:*"
            )
        )
    ) == 1
    assert float(
        redis_client.hget(
            provider_loop.PACED_CU_ADMISSION_WINDOW_PREFIX,
            "credit_cu",
        )
    ) == pytest.approx(0.0)

    admitted_chain = admitted_chains[0]
    admitted = results[admitted_chain]
    assert provider_loop._finalize_paced_compute_units(
        redis_client,
        chain=admitted_chain,
        lease_token=leases[admitted_chain],
        window_id=admitted[3],
        cost_cu=100,
        reservation_id=admitted[4],
    ) is True
    assert list(
        redis_client.scan_iter(
            f"{provider_loop.PACED_CU_RESERVATION_KEY_PREFIX}:*"
        )
    ) == []


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
    seed_path.write_text(json.dumps(_empty_candidate_watchlist_seed()), encoding="utf-8")
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
    seed_path.write_text(json.dumps(_empty_candidate_watchlist_seed()), encoding="utf-8")
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
    seed_path.write_text(json.dumps(_empty_candidate_watchlist_seed()), encoding="utf-8")
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
