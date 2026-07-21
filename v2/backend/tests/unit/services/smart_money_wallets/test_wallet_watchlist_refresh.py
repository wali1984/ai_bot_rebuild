from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from app.cli import v2_moralis_provider_loop as provider_loop
from app.services.smart_money_wallets import wallet_watchlist as watchlist_module
from app.services.smart_money_wallets.wallet_watchlist import (
    DEFAULT_WATCHLIST_TTL_SECONDS,
    WALLET_WATCHLIST_KEY,
    WALLET_WATCHLIST_STATUS_KEY,
    WalletWatchlistSeedError,
    load_wallet_watchlist_seed,
    read_wallet_watchlist,
    refresh_candidate_wallet_watchlist,
)

ADDRESS = "0x" + ("2" * 40)
OTHER_ADDRESS = "0x" + ("3" * 40)
OBSERVED_AT = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


class FakePipeline:
    def __init__(self, redis_client: FakeRedis) -> None:
        self.redis_client = redis_client
        self.operations: list[tuple[str, str, int | None]] = []

    def set(self, key: str, value: str, ex: int | None = None) -> FakePipeline:
        self.operations.append((key, value, ex))
        return self

    def execute(self) -> list[bool]:
        self.redis_client.pipeline_execute_count += 1
        return [self.redis_client.set(key, value, ex=ttl) for key, value, ttl in self.operations]


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.set_count = 0
        self.pipeline_execute_count = 0

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.set_count += 1
        self.data[key] = value
        if ex is not None:
            self.ttls[key] = int(ex)
        return True

    def ttl(self, key: str) -> int:
        if key not in self.data:
            return -2
        return self.ttls.get(key, -1)

    def pipeline(self, *, transaction: bool) -> FakePipeline:
        assert transaction is True
        return FakePipeline(self)


class NonTransactionalRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        del ex
        self.data[key] = value
        return True

    def ttl(self, key: str) -> int:
        return -2 if key not in self.data else 3600


class TtlFailureRedis(FakeRedis):
    def ttl(self, key: str) -> int:
        del key
        raise RuntimeError("redis ttl unavailable")


class NoDispatchLimiter:
    cu = None

    @staticmethod
    def as_dict() -> dict[str, Any]:
        return {
            "provider_polling_blocked": False,
            "cu_ledger_required": True,
            "compute_budget": {
                "daily_budget": 55_000,
                "daily_reserve": 10_000,
                "monthly_budget": 2_000_000,
            },
            "persistent_cu_ledger": {
                "ledger_available": True,
                "daily_limit_cu": 45_000,
                "remaining_today_cu": 25_000,
                "monthly_limit_cu": 2_000_000,
                "remaining_month_cu": 1_900_000,
            },
        }


class NoDispatchClient:
    limiter = NoDispatchLimiter()

    @staticmethod
    def get(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("watchlist refresh must not dispatch provider I/O")


class BlockedNoDispatchLimiter(NoDispatchLimiter):
    @staticmethod
    def as_dict() -> dict[str, Any]:
        payload = NoDispatchLimiter.as_dict()
        payload["provider_polling_blocked"] = True
        return payload


class BlockedNoDispatchClient(NoDispatchClient):
    limiter = BlockedNoDispatchLimiter()


def _write_seed(
    path: Path,
    *,
    wallets: list[dict[str, Any]] | None = None,
    schema_version: str = "moralis_wallet_watchlist_seed_v1",
) -> None:
    selected_wallets = wallets
    if selected_wallets is None:
        selected_wallets = [
            {
                "chain": "eth",
                "address": ADDRESS,
                "tier": "T0",
                "source": "unit_source:rank=1",
                "classification": "CANDIDATE_SMART_WALLET",
                "verified_smart_wallet": False,
                "added_utc": "2026-07-20T12:00:00Z",
                "added_by": "v2_moralis_wallet_watchlist_bootstrap",
            }
        ]
    path.write_text(
        json.dumps(
            {
                "schema_version": schema_version,
                "policy": {
                    "empty_watchlist_status": "CONFIGURED_NO_WATCHLIST",
                    "t0_max_wallets": 50,
                    "t1_max_wallets": 250,
                    "unknown_wallet_is_smart_money": False,
                },
                "wallets": selected_wallets,
            }
        ),
        encoding="utf-8",
    )


def test_repository_seed_is_candidate_only_and_preserves_chain_identity() -> None:
    rows = load_wallet_watchlist_seed(observed_at=OBSERVED_AT)

    assert len(rows) == 270
    assert sum(row["chain"] == "eth" for row in rows) == 239
    assert sum(row["chain"] == "optimism" for row in rows) == 17
    assert sum(row["chain"] == "arbitrum" for row in rows) == 14
    assert all(row["candidate_wallet"] is True for row in rows)
    assert all(row["verified_smart_wallet"] is False for row in rows)
    assert all(row["counts_as_smart_money"] is False for row in rows)
    assert all(row["point_in_time_safe"] is True for row in rows)


@pytest.mark.parametrize("invalid_value", [0, 1, "false", None, [], {}])
def test_metadata_is_contract_requires_an_actual_bool_when_present(
    tmp_path: Path,
    invalid_value: Any,
) -> None:
    seed_path = tmp_path / "watchlist.json"
    row = {
        "chain": "eth",
        "address": ADDRESS,
        "tier": "T0",
        "source": "unit_source:rank=1",
        "classification": "CANDIDATE_SMART_WALLET",
        "verified_smart_wallet": False,
        "added_utc": "2026-07-20T12:00:00Z",
        "added_by": "v2_moralis_wallet_watchlist_bootstrap",
        "metadata": {"is_contract": invalid_value},
    }
    _write_seed(seed_path, wallets=[row])

    with pytest.raises(
        WalletWatchlistSeedError,
        match="WATCHLIST_SEED_METADATA_INVALID",
    ):
        load_wallet_watchlist_seed(seed_path, observed_at=OBSERVED_AT)


def test_tracked_seed_schema_valid_replacement_fails_digest_pin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracked_path = watchlist_module._TRACKED_DEFAULT_SEED_PATH
    original_reader = watchlist_module._read_exact_seed_bytes
    payload = json.loads(tracked_path.read_text(encoding="utf-8"))
    payload["review_nonce"] = "schema-valid-local-replacement"
    replaced = json.dumps(payload).encode("utf-8")

    def _read(path: Path) -> tuple[bytes, Path]:
        if Path(path).resolve() == tracked_path:
            return replaced, tracked_path
        return original_reader(Path(path))

    monkeypatch.setattr(watchlist_module, "_read_exact_seed_bytes", _read)

    with pytest.raises(
        WalletWatchlistSeedError,
        match="WATCHLIST_SEED_AUTHENTICITY_INVALID",
    ):
        load_wallet_watchlist_seed(observed_at=OBSERVED_AT)


@pytest.mark.parametrize(
    "tracked_path",
    [
        watchlist_module._TRACKED_DEFAULT_EXCLUDED_PATH,
        watchlist_module._TRACKED_DEFAULT_EXCHANGE_PATH,
    ],
)
def test_tracked_classifier_schema_valid_replacement_fails_digest_pin(
    monkeypatch: pytest.MonkeyPatch,
    tracked_path: Path,
) -> None:
    original_reader = watchlist_module._read_exact_seed_bytes
    payload = json.loads(tracked_path.read_text(encoding="utf-8"))
    payload["review_nonce"] = "schema-valid-local-replacement"
    replaced = json.dumps(payload).encode("utf-8")

    def _read(path: Path) -> tuple[bytes, Path]:
        if Path(path).resolve() == tracked_path:
            return replaced, tracked_path
        return original_reader(Path(path))

    monkeypatch.setattr(watchlist_module, "_read_exact_seed_bytes", _read)

    with pytest.raises(
        WalletWatchlistSeedError,
        match="WATCHLIST_CLASSIFIER_AUTHORITY_AUTHENTICITY_INVALID",
    ):
        load_wallet_watchlist_seed(observed_at=OBSERVED_AT)


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        ("schema", "WATCHLIST_SEED_SCHEMA_INVALID"),
        ("verified", "WATCHLIST_SEED_CANDIDATE_SEMANTICS_INVALID"),
        ("future", "WATCHLIST_SEED_POINT_IN_TIME_INVALID"),
        ("missing_source", "WATCHLIST_SEED_SOURCE_INVALID"),
    ],
)
def test_invalid_seed_fails_closed_without_runtime_watchlist(
    tmp_path: Path,
    mutation: str,
    expected_reason: str,
) -> None:
    seed_path = tmp_path / "watchlist.json"
    row = {
        "chain": "eth",
        "address": ADDRESS,
        "tier": "T0",
        "source": "unit_source:rank=1",
        "classification": "CANDIDATE_SMART_WALLET",
        "verified_smart_wallet": False,
        "added_utc": "2026-07-20T12:00:00Z",
        "added_by": "v2_moralis_wallet_watchlist_bootstrap",
    }
    schema = "moralis_wallet_watchlist_seed_v1"
    if mutation == "schema":
        schema = "forged_schema"
    elif mutation == "verified":
        row["verified_smart_wallet"] = True
    elif mutation == "future":
        row["added_utc"] = "2026-07-22T12:00:00Z"
    elif mutation == "missing_source":
        row["source"] = ""
    _write_seed(seed_path, wallets=[row], schema_version=schema)
    redis_client = FakeRedis()

    status = refresh_candidate_wallet_watchlist(
        redis_client,
        path=seed_path,
        observed_at=OBSERVED_AT,
    )

    assert status["status"] == "WATCHLIST_SEED_REJECTED"
    assert status["rejection_reason"] == expected_reason
    assert status["refresh_succeeded"] is False
    assert WALLET_WATCHLIST_KEY not in redis_client.data
    assert status["compute_units_reserved"] == 0
    assert status["moralis_request_count"] == 0
    assert status["trainer_isolation_changed"] is False


def test_symlink_seed_path_fails_closed(tmp_path: Path) -> None:
    seed_path = tmp_path / "watchlist.json"
    link_path = tmp_path / "watchlist-link.json"
    _write_seed(seed_path)
    link_path.symlink_to(seed_path)
    redis_client = FakeRedis()

    status = refresh_candidate_wallet_watchlist(
        redis_client,
        path=link_path,
        observed_at=OBSERVED_AT,
    )

    assert status["rejection_reason"] == "WATCHLIST_SEED_PATH_NOT_CANONICAL"
    assert status["refresh_succeeded"] is False
    assert WALLET_WATCHLIST_KEY not in redis_client.data
    with pytest.raises(WalletWatchlistSeedError, match="WATCHLIST_SEED_PATH_NOT_CANONICAL"):
        load_wallet_watchlist_seed(link_path, observed_at=OBSERVED_AT)


def test_missing_classifier_authority_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_path = tmp_path / "watchlist.json"
    _write_seed(seed_path)
    monkeypatch.setattr(
        watchlist_module,
        "DEFAULT_EXCLUDED_PATH",
        tmp_path / "missing-exclusions.json",
    )
    redis_client = FakeRedis()

    status = refresh_candidate_wallet_watchlist(redis_client, path=seed_path)

    assert status["status"] == "WATCHLIST_SEED_REJECTED"
    assert status["rejection_reason"] == "WATCHLIST_CLASSIFIER_AUTHORITY_UNAVAILABLE"
    assert WALLET_WATCHLIST_KEY not in redis_client.data


def test_schema_valid_classifier_replacement_that_blocks_candidate_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_path = tmp_path / "watchlist.json"
    excluded_path = tmp_path / "excluded.json"
    exchange_path = tmp_path / "exchange.json"
    _write_seed(seed_path)
    excluded_path.write_text(
        json.dumps(
            {
                "schema_version": "moralis_excluded_addresses_v1",
                "addresses": [
                    {
                        "chain": "eth",
                        "address": ADDRESS,
                        "category": "deployer",
                        "label": "fixture",
                        "source": "unit_classifier_replacement",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    exchange_path.write_text(
        json.dumps(
            {
                "schema_version": "moralis_exchange_wallets_v1",
                "policy": {
                    "exchange_wallets_are_smart_money": False,
                    "require_source_for_exchange_wallet": True,
                },
                "addresses": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(watchlist_module, "DEFAULT_EXCLUDED_PATH", excluded_path)
    monkeypatch.setattr(watchlist_module, "DEFAULT_EXCHANGE_PATH", exchange_path)

    status = refresh_candidate_wallet_watchlist(FakeRedis(), path=seed_path)

    assert status["status"] == "WATCHLIST_SEED_REJECTED"
    assert status["rejection_reason"] == "WATCHLIST_SEED_CLASSIFICATION_REJECTED"


def test_transactional_redis_is_required_for_pair_publication(tmp_path: Path) -> None:
    seed_path = tmp_path / "watchlist.json"
    _write_seed(seed_path)
    redis_client = NonTransactionalRedis()

    status = refresh_candidate_wallet_watchlist(redis_client, path=seed_path)

    assert status["refresh_action"] == "REDIS_WRITE_FAILED"
    assert status["refresh_succeeded"] is False
    assert WALLET_WATCHLIST_KEY not in redis_client.data


def test_ttl_redis_error_triggers_safe_transactional_refresh(tmp_path: Path) -> None:
    seed_path = tmp_path / "watchlist.json"
    _write_seed(seed_path)
    redis_client = TtlFailureRedis()
    first = refresh_candidate_wallet_watchlist(redis_client, path=seed_path)

    second = refresh_candidate_wallet_watchlist(redis_client, path=seed_path)

    assert first["refresh_succeeded"] is True
    assert second["refresh_action"] == "REFRESHED_EXPIRING_RUNTIME_COPY"
    assert second["refresh_succeeded"] is True


def test_refresh_repairs_tampered_runtime_copy_and_expiring_ttl(tmp_path: Path) -> None:
    seed_path = tmp_path / "watchlist.json"
    _write_seed(seed_path)
    redis_client = FakeRedis()
    first = refresh_candidate_wallet_watchlist(
        redis_client,
        path=seed_path,
    )
    assert first["refresh_action"] == "REFRESHED_MISSING_OR_INVALID_RUNTIME_COPY"
    assert read_wallet_watchlist(redis_client, path=seed_path) == [
        {
            "chain": "eth",
            "address": ADDRESS,
            "tier": "T0",
            "source": "unit_source:rank=1",
        }
    ]

    forged = json.loads(redis_client.data[WALLET_WATCHLIST_KEY])
    forged["rows"][0]["address"] = OTHER_ADDRESS
    redis_client.data[WALLET_WATCHLIST_KEY] = json.dumps(forged)
    repaired = refresh_candidate_wallet_watchlist(
        redis_client,
        path=seed_path,
    )
    assert repaired["refresh_action"] == "REFRESHED_MISSING_OR_INVALID_RUNTIME_COPY"
    assert read_wallet_watchlist(redis_client, path=seed_path)[0]["address"] == ADDRESS

    writes_before_retained = redis_client.set_count
    retained = refresh_candidate_wallet_watchlist(
        redis_client,
        path=seed_path,
    )
    assert retained["refresh_action"] == "RETAINED_VALID_RUNTIME_COPY"
    assert redis_client.set_count == writes_before_retained

    redis_client.ttls[WALLET_WATCHLIST_KEY] = 1
    redis_client.ttls[WALLET_WATCHLIST_STATUS_KEY] = 1
    refreshed = refresh_candidate_wallet_watchlist(
        redis_client,
        path=seed_path,
    )
    assert refreshed["refresh_action"] == "REFRESHED_EXPIRING_RUNTIME_COPY"
    assert redis_client.ttls[WALLET_WATCHLIST_KEY] == DEFAULT_WATCHLIST_TTL_SECONDS


def test_empty_seed_is_valid_gray_and_never_invents_a_wallet(tmp_path: Path) -> None:
    seed_path = tmp_path / "watchlist.json"
    _write_seed(seed_path, wallets=[])
    redis_client = FakeRedis()

    status = refresh_candidate_wallet_watchlist(
        redis_client,
        path=seed_path,
    )

    assert status["status"] == "CONFIGURED_NO_WATCHLIST"
    assert status["dashboard_color"] == "GRAY"
    assert status["candidate_wallet_count"] == 0
    assert status["verified_smart_wallet_count"] == 0
    assert read_wallet_watchlist(redis_client, path=seed_path) == []
    payload = json.loads(redis_client.data[WALLET_WATCHLIST_KEY])
    assert payload["rows"] == []


def test_refresh_preserves_cu_cadence_and_address_free_status(tmp_path: Path) -> None:
    seed_path = tmp_path / "watchlist.json"
    _write_seed(seed_path)
    redis_client = FakeRedis()
    redis_client.data["v2:provider:moralis:cu_budget_status"] = "CU_SENTINEL"
    redis_client.data["v2:provider:moralis:rotation_cursor:eth"] = "CURSOR_SENTINEL"
    redis_client.data["v2:provider:moralis:cadence_claim:eth:fixture"] = "CLAIM_SENTINEL"

    status = refresh_candidate_wallet_watchlist(
        redis_client,
        path=seed_path,
    )
    stored_status = json.loads(redis_client.data[WALLET_WATCHLIST_STATUS_KEY])
    encoded_status = json.dumps(stored_status, sort_keys=True)

    assert status["compute_units_reserved"] == 0
    assert status["moralis_request_count"] == 0
    assert status["cadence_claims_mutated"] is False
    assert status["trainer_isolation_changed"] is False
    assert redis_client.data["v2:provider:moralis:cu_budget_status"] == "CU_SENTINEL"
    assert redis_client.data["v2:provider:moralis:rotation_cursor:eth"] == "CURSOR_SENTINEL"
    assert redis_client.data["v2:provider:moralis:cadence_claim:eth:fixture"] == "CLAIM_SENTINEL"
    assert ADDRESS not in encoded_status
    assert "rows" not in stored_status
    assert "source_path" not in stored_status
    assert stored_status["raw_address_exposed_in_status"] is False
    assert stored_status["raw_key_exposed"] is False
    assert stored_status["verified_smart_wallet_count"] == 0
    assert stored_status["counts_as_smart_money_count"] == 0
    assert stored_status["starter_budget_supported"] is None
    assert stored_status["starter_budget_support_evaluated_here"] is False
    assert stored_status["candidate_polling_subject_to_durable_cu_ledger"] is True


def test_local_seed_tamper_quarantines_previously_published_rows(tmp_path: Path) -> None:
    seed_path = tmp_path / "watchlist.json"
    _write_seed(seed_path)
    redis_client = FakeRedis()
    refresh_candidate_wallet_watchlist(
        redis_client,
        path=seed_path,
    )
    _write_seed(seed_path, schema_version="tampered")

    status = refresh_candidate_wallet_watchlist(
        redis_client,
        path=seed_path,
    )

    assert status["status"] == "WATCHLIST_SEED_REJECTED"
    assert read_wallet_watchlist(redis_client, path=seed_path) == []


def test_provider_maintenance_reports_candidate_semantics_without_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refresh_calls: list[Any] = []

    def _refresh(redis_client: Any) -> dict[str, Any]:
        refresh_calls.append(redis_client)
        return {
            "refresh_action": "RETAINED_VALID_RUNTIME_COPY",
            "refresh_succeeded": True,
            "compute_units_reserved": 0,
            "moralis_request_count": 0,
        }

    monkeypatch.setattr(provider_loop, "refresh_candidate_wallet_watchlist", _refresh)
    monkeypatch.setattr(
        provider_loop,
        "read_wallet_watchlist",
        lambda redis_client: [
            {"chain": "eth", "address": ADDRESS, "tier": "T0", "source": "eth_source"},
            {
                "chain": "arbitrum",
                "address": OTHER_ADDRESS,
                "tier": "T1",
                "source": "arb_source",
            },
        ],
    )
    monkeypatch.setattr(provider_loop, "read_pollable_tokens", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        provider_loop,
        "read_metadata_validation_tokens",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(provider_loop, "moralis_endpoint_registry", lambda: ())

    status = provider_loop.run_once(
        None,
        client=NoDispatchClient(),
        chain="eth",
        wallets=[],
        tokens=[],
        symbol="BTCUSDT",
        maintain_candidate_watchlist=True,
    )

    assert refresh_calls == [None]
    assert status["wallet_count"] == 1
    assert status["candidate_wallet_count"] == 2
    assert status["candidate_wallet_chain_counts"] == {"arbitrum": 1, "eth": 1}
    assert status["active_candidate_chain"] == "eth"
    assert status["active_candidate_wallet_count"] == 1
    assert status["queued_candidate_wallet_count"] == 1
    assert status["queued_candidate_wallet_chain_counts"] == {"arbitrum": 1}
    assert status["queued_candidate_wallet_polling_status"] == (
        "QUEUED_NOT_POLLED_BY_THIS_CHAIN_LOOP"
    )
    assert status["all_candidate_chains_runtime_active"] is False
    assert status["cross_chain_runtime_services_started_by_this_change"] == 0
    assert status["verified_smart_wallet_count"] == 0
    assert status["wallet_watchlist_semantics"] == "CANDIDATE_OBSERVATION_TARGETS_ONLY"
    assert status["watchlist_refresh_action"] == "RETAINED_VALID_RUNTIME_COPY"
    assert status["watchlist_refresh_compute_units_reserved"] == 0
    assert status["watchlist_refresh_moralis_request_count"] == 0
    loop_status = provider_loop._loop_log_report(status)
    assert ADDRESS not in json.dumps(loop_status, sort_keys=True)
    assert OTHER_ADDRESS not in json.dumps(loop_status, sort_keys=True)


def test_provider_run_restores_repository_seed_before_budget_blocked_schedule() -> None:
    redis_client = FakeRedis()

    status = provider_loop.run_once(
        redis_client,
        client=BlockedNoDispatchClient(),
        chain="eth",
        wallets=[],
        tokens=[],
        symbol="BTCUSDT",
        maintain_candidate_watchlist=True,
    )

    assert status["wallet_count"] == 239
    assert status["candidate_wallet_count"] == 270
    assert status["candidate_wallet_chain_counts"] == {
        "arbitrum": 14,
        "eth": 239,
        "optimism": 17,
    }
    assert status["active_candidate_wallet_count"] == 239
    assert status["queued_candidate_wallet_count"] == 31
    assert status["queued_candidate_wallet_chain_counts"] == {
        "arbitrum": 14,
        "optimism": 17,
    }
    assert status["verified_smart_wallet_count"] == 0
    assert status["request_count"] == 0
    assert status["scheduler_run_suppressed_reason"] == "BUDGET_AUTHORITY_UNAVAILABLE"
    assert status["watchlist_refresh_succeeded"] is True
    assert status["watchlist_refresh_compute_units_reserved"] == 0
    assert WALLET_WATCHLIST_KEY in redis_client.data
