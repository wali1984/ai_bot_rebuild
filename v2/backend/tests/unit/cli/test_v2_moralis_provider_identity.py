from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from v2.backend.app.cli import v2_moralis_provider_loop as provider_loop
from v2.backend.app.services.smart_money_wallets.endpoint_registry import (
    MoralisEndpointSpec,
)
from v2.backend.app.services.smart_money_wallets.models import MoralisResponse

BTC_TOKEN = "0x" + ("a" * 40)
LINK_TOKEN = "0x" + ("b" * 40)
LINK_TOKEN_UPPER = "0x" + ("B" * 40)
SHARED_TOKEN = "0x" + ("c" * 40)
UNMAPPED_TOKEN = "0x" + ("d" * 40)

TOKEN_SPEC = MoralisEndpointSpec(
    endpoint_id="token_transfers",
    group="token_transfers",
    path_template="/erc20/{token}/transfers?chain={chain}",
    purpose="identity test",
    priority="MEDIUM_HIGH",
    cu_cost=50,
    cadence_seconds_tier0=600,
    cadence_seconds_tier1=900,
    cadence_seconds_full_watchlist=21600,
    ttl_seconds=3600,
    feature_outputs=("moralis_net_exchange_flow_usd",),
    requires_token=True,
)


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def set(
        self,
        key: str,
        value: str,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool:
        del ex
        if nx and key in self.data:
            return False
        self.data[key] = value
        return True

    def delete(self, key: str) -> int:
        return int(self.data.pop(key, None) is not None)

    def eval(self, script: str, numkeys: int, *args: Any) -> Any:
        keys = [str(item) for item in args[:numkeys]]
        argv = [str(item) for item in args[numkeys:]]
        if "MORALIS_FENCED_CADENCE_CLAIM_V1" in script:
            if self.data.get(keys[0]) != argv[0]:
                return [-1, 0]
            if keys[1] in self.data:
                return [0, 1]
            self.data[keys[1]] = argv[1]
            return [1, 1]
        if "MORALIS_FENCED_CURSOR_WRITE_V1" in script:
            if self.data.get(keys[0]) != argv[0]:
                return 0
            self.data[keys[1]] = argv[1]
            return 1
        if "EXPIRE" in script:
            return int(self.data.get(keys[0]) == argv[0])
        if "DEL" in script:
            if self.data.get(keys[0]) != argv[0]:
                return 0
            return self.delete(keys[0])
        raise AssertionError("unexpected Redis script")


class FakeLimiter:
    def as_dict(self) -> dict[str, Any]:
        return {
            "normal_rps": 5,
            "catchup_rps": 10,
            "hard_rps": 30,
            "current_rps": 5,
            "cu_ledger_required": False,
            "provider_polling_blocked": False,
            "compute_budget": {
                "daily_budget": 55_000,
                "daily_reserve": 10_000,
                "monthly_budget": 2_000_000,
                "remaining_today": 45_000,
                "remaining_month": 2_000_000,
                "used_today": 0,
                "used_month": 0,
            },
        }


class RecordingClient:
    def __init__(self) -> None:
        self.limiter = FakeLimiter()
        self.calls: list[dict[str, Any]] = []

    def get(
        self,
        spec: MoralisEndpointSpec,
        *,
        chain: str,
        wallet: str | None = None,
        token: str | None = None,
        symbol: str | None = None,
    ) -> MoralisResponse:
        self.calls.append(
            {
                "endpoint_id": spec.endpoint_id,
                "chain": chain,
                "wallet": wallet,
                "token": token,
                "symbol": symbol,
            }
        )
        return MoralisResponse(
            spec.endpoint_id,
            chain,
            wallet,
            token,
            symbol,
            200,
            {"result": []},
            request_dispatched=True,
        )


class CycleBudgetClient:
    def __init__(self) -> None:
        self.limiter = FakeLimiter()
        self.remaining_dispatches = 0
        self.dispatched_tokens: list[str] = []
        self.calls: list[str | None] = []

    def begin_cycle(self, *, dispatches: int) -> None:
        self.remaining_dispatches = dispatches

    def get(
        self,
        spec: MoralisEndpointSpec,
        *,
        chain: str,
        wallet: str | None = None,
        token: str | None = None,
        symbol: str | None = None,
    ) -> MoralisResponse:
        self.calls.append(token)
        dispatched = self.remaining_dispatches > 0
        if dispatched:
            self.remaining_dispatches -= 1
            if token is not None:
                self.dispatched_tokens.append(token)
        return MoralisResponse(
            spec.endpoint_id,
            chain,
            wallet,
            token,
            symbol,
            200 if dispatched else None,
            {"result": []} if dispatched else None,
            error_class=None if dispatched else "RPS_CAP",
            request_dispatched=dispatched,
        )


def _seed_token_map(
    redis_client: FakeRedis,
    rows: list[tuple[str, str, str]],
) -> None:
    symbols = sorted({symbol for symbol, _chain, _contract in rows})
    redis_client.data["v2:moralis:token_map_status"] = json.dumps(
        {"token_map_count": len(symbols), "symbols": symbols}
    )
    for symbol in symbols:
        contracts = [
            {
                "chain": chain,
                "contract_address": contract,
                "pollable": True,
                "tradeable_mapping_status": "VERIFIED",
            }
            for row_symbol, chain, contract in rows
            if row_symbol == symbol
        ]
        redis_client.data[f"v2:moralis:token_map:{symbol}"] = json.dumps(
            {"symbol": symbol, "contracts": contracts}
        )


@pytest.fixture(autouse=True)
def _provider_identity_fixture_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep provider-loop identity tests focused on scheduler semantics.

    Strict token-map provenance and canonical metadata evidence are exercised
    in the mapper tests; synthetic addresses in this module are intentionally
    supplied through a fixture reader instead of pretending to be production
    Redis attestations.
    """

    def _read(redis_client: FakeRedis, *, symbol: str | None = None) -> list[dict[str, str]]:
        status = json.loads(redis_client.data.get("v2:moralis:token_map_status", "{}"))
        symbols = [symbol] if symbol else status.get("symbols") or []
        rows: list[dict[str, str]] = []
        for item in symbols:
            payload = json.loads(
                redis_client.data.get(f"v2:moralis:token_map:{str(item).upper()}", "{}")
            )
            for contract in payload.get("contracts") or []:
                if contract.get("pollable") is True:
                    rows.append(
                        {
                            "symbol": str(payload.get("symbol") or item).upper(),
                            "chain": str(contract.get("chain") or ""),
                            "token": str(contract.get("contract_address") or ""),
                        }
                    )
        return rows

    monkeypatch.setattr(provider_loop, "read_pollable_tokens", _read)
    monkeypatch.setattr(provider_loop, "read_metadata_validation_tokens", _read)


def _patch_single_token_endpoint(monkeypatch: Any) -> None:
    monkeypatch.setattr(provider_loop, "moralis_endpoint_registry", lambda: (TOKEN_SPEC,))
    monkeypatch.setattr(
        provider_loop,
        "publish_moralis_feature_payload",
        lambda *args, **kwargs: {},
    )


def test_explicit_token_uses_complete_token_map_not_context_symbol_scope() -> None:
    redis_client = FakeRedis()
    _seed_token_map(
        redis_client,
        [
            ("BTCUSDT", "ethereum", BTC_TOKEN),
            ("LINKUSDT", "ethereum", LINK_TOKEN),
        ],
    )

    bootstrap = provider_loop._resolve_bootstrap_inputs(
        redis_client,
        chain="eth",
        symbol="BTCUSDT",
        wallets=[],
        tokens=[LINK_TOKEN_UPPER],
    )

    assert bootstrap["tokens"] == [LINK_TOKEN_UPPER]
    assert bootstrap["contract_symbol_map"][("eth", LINK_TOKEN)]["symbol"] == "LINKUSDT"
    assert bootstrap["ambiguous_contract_keys"] == set()


def test_duplicate_contract_identity_is_ambiguous_and_never_requested(monkeypatch: Any) -> None:
    redis_client = FakeRedis()
    _seed_token_map(
        redis_client,
        [
            ("LINKUSDT", "ethereum", SHARED_TOKEN),
            ("FAKEUSDT", "eth", SHARED_TOKEN),
        ],
    )
    client = RecordingClient()
    published: list[dict[str, Any]] = []
    _patch_single_token_endpoint(monkeypatch)
    monkeypatch.setattr(
        provider_loop,
        "publish_moralis_result",
        lambda *args, **kwargs: published.append(kwargs),
    )

    status = provider_loop.run_once(
        redis_client,
        client=client,
        chain="eth",
        wallets=[],
        tokens=[SHARED_TOKEN],
        symbol="BTCUSDT",
    )

    assert client.calls == []
    assert published == []
    assert status["request_count"] == 0
    assert status["ambiguous_contract_identity_count"] == 1
    assert status["identity_rejected_request_count"] == 1
    assert status["quarantined_contracts"][0]["reason"] == "AMBIGUOUS_VERIFIED_SYMBOL_MAPPING"


def test_unmapped_explicit_token_is_quarantined_before_client_or_cu_path(monkeypatch: Any) -> None:
    redis_client = FakeRedis()
    _seed_token_map(redis_client, [("BTCUSDT", "ethereum", BTC_TOKEN)])
    client = RecordingClient()
    published: list[dict[str, Any]] = []
    bridge_refreshes: list[dict[str, Any]] = []
    _patch_single_token_endpoint(monkeypatch)
    monkeypatch.setattr(
        provider_loop,
        "publish_moralis_result",
        lambda *args, **kwargs: published.append(kwargs),
    )
    monkeypatch.setattr(
        provider_loop,
        "publish_moralis_feature_payload",
        lambda *args, **kwargs: bridge_refreshes.append(kwargs),
    )

    status = provider_loop.run_once(
        redis_client,
        client=client,
        chain="eth",
        wallets=[],
        tokens=[UNMAPPED_TOKEN],
        symbol="BTCUSDT",
    )

    assert client.calls == []
    assert published == []
    assert bridge_refreshes[0]["features"] == {}
    assert bridge_refreshes[0]["actual_payload_present"] is False
    assert status["request_count"] == 0
    assert status["identity_rejected_request_count"] == 1
    assert status["quarantined_contracts"][0]["reason"] == "NO_VERIFIED_SYMBOL_MAPPING"


def test_malformed_target_is_quarantined_before_client_publish_or_redis_key(
    monkeypatch: Any,
) -> None:
    redis_client = FakeRedis()
    _seed_token_map(redis_client, [("LINKUSDT", "ethereum", LINK_TOKEN)])
    client = RecordingClient()
    published: list[dict[str, Any]] = []
    injected_target = f"{LINK_TOKEN}?chain=polygon"
    _patch_single_token_endpoint(monkeypatch)
    monkeypatch.setattr(
        provider_loop,
        "publish_moralis_result",
        lambda *args, **kwargs: published.append(kwargs),
    )

    status = provider_loop.run_once(
        redis_client,
        client=client,
        chain="eth",
        wallets=[],
        tokens=[injected_target],
        symbol="BTCUSDT",
    )

    assert client.calls == []
    assert published == []
    assert status["request_count"] == 0
    assert status["quarantined_contracts"][0]["reason"] == "TOKEN_ADDRESS_INVALID"
    assert "target_fingerprint" in status["quarantined_contracts"][0]
    assert injected_target not in json.dumps(status)


def test_verified_token_is_requested_and_published_under_its_own_symbol(monkeypatch: Any) -> None:
    redis_client = FakeRedis()
    _seed_token_map(
        redis_client,
        [
            ("BTCUSDT", "ethereum", BTC_TOKEN),
            ("LINKUSDT", "ethereum", LINK_TOKEN),
        ],
    )
    client = RecordingClient()
    published: list[dict[str, Any]] = []
    _patch_single_token_endpoint(monkeypatch)

    def _record_publish(*args: Any, **kwargs: Any) -> dict[str, Any]:
        del args
        published.append(kwargs)
        return {"actual_payload_present": True}

    monkeypatch.setattr(provider_loop, "publish_moralis_result", _record_publish)

    status = provider_loop.run_once(
        redis_client,
        client=client,
        chain="eth",
        wallets=[],
        tokens=[LINK_TOKEN_UPPER],
        symbol="BTCUSDT",
    )

    assert [call["symbol"] for call in client.calls] == ["LINKUSDT"]
    assert [row["symbol"] for row in published] == ["LINKUSDT"]
    assert status["resolved_symbols"] == ["LINKUSDT"]
    assert status["quarantined_contract_count"] == 0


def test_unsupported_endpoint_contract_is_quarantined_before_client_or_publish(
    monkeypatch: Any,
) -> None:
    redis_client = FakeRedis()
    _seed_token_map(redis_client, [("LINKUSDT", "ethereum", LINK_TOKEN)])
    client = RecordingClient()
    published: list[dict[str, Any]] = []
    unsupported_spec = replace(
        TOKEN_SPEC,
        http_method="POST",
        request_body_shape='{"tokens":[{"token_address":"{token}"}]}',
        polling_supported=False,
        polling_block_reason="ENDPOINT_POST_BATCH_BODY_AND_SCHEDULING_UNSUPPORTED",
    )
    monkeypatch.setattr(provider_loop, "moralis_endpoint_registry", lambda: (unsupported_spec,))
    monkeypatch.setattr(
        provider_loop,
        "publish_moralis_result",
        lambda *args, **kwargs: published.append(kwargs),
    )
    monkeypatch.setattr(
        provider_loop,
        "publish_moralis_feature_payload",
        lambda *args, **kwargs: {},
    )

    status = provider_loop.run_once(
        redis_client,
        client=client,
        chain="eth",
        wallets=[],
        tokens=[LINK_TOKEN],
        symbol="BTCUSDT",
    )

    assert client.calls == []
    assert published == []
    assert status["request_count"] == 0
    assert status["unsupported_endpoint_contract_count"] == 1
    assert status["unsupported_endpoint_contracts"] == [
        {
            "endpoint_id": "token_transfers",
            "http_method": "POST",
            "reason": "ENDPOINT_POST_BATCH_BODY_AND_SCHEDULING_UNSUPPORTED",
        }
    ]
    assert status["schedule_plan"]["estimated_compute_units_per_cycle"] == 0


def test_duplicate_transport_alias_never_calls_client_or_reserves_separate_cu(
    monkeypatch: Any,
) -> None:
    redis_client = FakeRedis()
    _seed_token_map(redis_client, [("LINKUSDT", "ethereum", LINK_TOKEN)])
    client = RecordingClient()
    alias = replace(
        TOKEN_SPEC,
        endpoint_id="token_address_transfers",
        group="token_address_transfers",
        polling_supported=False,
        polling_block_reason="DUPLICATE_TRANSPORT_ALIAS_NOT_DIRECTLY_POLLED",
        transport_alias_of="token_transfers",
    )
    monkeypatch.setattr(
        provider_loop,
        "moralis_endpoint_registry",
        lambda: (TOKEN_SPEC, alias),
    )
    monkeypatch.setattr(
        provider_loop,
        "publish_moralis_result",
        lambda *args, **kwargs: {"actual_payload_present": False},
    )

    status = provider_loop.run_once(
        redis_client,
        client=client,
        chain="eth",
        wallets=[],
        tokens=[LINK_TOKEN],
        symbol="BTCUSDT",
    )

    assert [call["endpoint_id"] for call in client.calls] == ["token_transfers"]
    assert status["request_count"] == 1
    assert status["deduplicated_endpoint_contract_count"] == 1
    assert status["deduplicated_endpoint_contracts"][0]["transport_alias_of"] == ("token_transfers")
    alias_plan = next(
        row
        for row in status["schedule_plan"]["endpoints"]
        if row["endpoint_id"] == "token_address_transfers"
    )
    assert alias_plan["target_count"] == 0
    assert alias_plan["estimated_compute_units_per_cycle"] == 0


def test_durable_rotation_eventually_dispatches_every_configured_target(
    monkeypatch: Any,
) -> None:
    redis_client = FakeRedis()
    tokens = [f"0x{index:040x}" for index in range(1, 6)]
    _seed_token_map(
        redis_client,
        [(f"TOKEN{index}USDT", "ethereum", token) for index, token in enumerate(tokens)],
    )
    client = CycleBudgetClient()
    _patch_single_token_endpoint(monkeypatch)
    monkeypatch.setattr(
        provider_loop,
        "publish_moralis_result",
        lambda *args, **kwargs: {"actual_payload_present": False},
    )

    statuses = []
    for _cycle in tokens:
        client.begin_cycle(dispatches=1)
        statuses.append(
            provider_loop.run_once(
                redis_client,
                client=client,
                chain="eth",
                wallets=[],
                tokens=tokens,
                symbol="BTCUSDT",
            )
        )

    assert client.dispatched_tokens == tokens
    assert all(status["request_count"] == 1 for status in statuses)
    assert statuses[0]["publication_count"] == len(tokens)
    assert all(1 <= status["publication_count"] <= len(tokens) for status in statuses)
    assert sum(status["durable_cadence_suppressed_count"] for status in statuses) > 0
    assert all(status["durable_fair_rotation"] is True for status in statuses)
    assert all(status["canonical_token_transfer_transport_owner"] is True for status in statuses)
    assert statuses[-1]["schedule_plan"]["endpoints"][0]["target_count"] == len(tokens)


def test_pre_dispatch_denial_does_not_advance_cadence_state(monkeypatch: Any) -> None:
    redis_client = FakeRedis()
    _seed_token_map(redis_client, [("LINKUSDT", "ethereum", LINK_TOKEN)])
    client = CycleBudgetClient()
    state: dict[str, float] = {}
    _patch_single_token_endpoint(monkeypatch)
    monkeypatch.setattr(
        provider_loop,
        "publish_moralis_result",
        lambda *args, **kwargs: {"actual_payload_present": False},
    )

    client.begin_cycle(dispatches=0)
    denied = provider_loop.run_once(
        redis_client,
        client=client,
        chain="eth",
        wallets=[],
        tokens=[LINK_TOKEN],
        symbol="BTCUSDT",
        scheduler_state=state,
        force=False,
        now_monotonic=100.0,
    )
    assert denied["request_count"] == 0
    assert denied["publication_count"] == 1
    assert denied["pre_dispatch_denial_publication_count"] == 1
    assert state == {}

    client.begin_cycle(dispatches=1)
    dispatched = provider_loop.run_once(
        redis_client,
        client=client,
        chain="eth",
        wallets=[],
        tokens=[LINK_TOKEN],
        symbol="BTCUSDT",
        scheduler_state=state,
        force=False,
        now_monotonic=101.0,
    )
    assert dispatched["request_count"] == 1
    assert len(state) == 1


def test_scheduler_plan_uses_durable_budget_authority_snapshot() -> None:
    status = {
        "cu_ledger_required": True,
        "normal_rps": 7,
        "catchup_rps": 11,
        "hard_rps": 17,
        "current_rps": 7,
        "compute_budget": {
            "daily_budget": 900,
            "daily_reserve": 100,
            "monthly_budget": 9_000,
            "remaining_today": 700,
            "remaining_month": 8_000,
        },
        "persistent_cu_ledger": {
            "ledger_available": True,
            "daily_limit_cu": 640,
            "remaining_today_cu": 540,
            "monthly_limit_cu": 8_500,
            "remaining_month_cu": 7_500,
        },
    }

    plan = provider_loop.moralis_scheduler_plan(
        wallets=[],
        tokens=[LINK_TOKEN],
        budget_status=status,
    )

    assert plan["budget_authority"] == "DURABLE_CU_LEDGER"
    assert plan["budget_authority_available"] is True
    assert plan["daily_compute_unit_budget"] == 900
    assert plan["daily_compute_unit_reserve"] == 100
    assert plan["effective_daily_compute_unit_limit"] == 640
    assert plan["remaining_today_compute_units"] == 540
    assert plan["monthly_compute_unit_budget"] == 8_500
    assert plan["remaining_month_compute_units"] == 7_500
    assert plan["normal_rps"] == 7
    assert plan["current_rps"] == 7
    assert plan["durable_fair_rotation"] is False


def test_scheduler_plan_fails_closed_when_required_durable_authority_unavailable() -> None:
    plan = provider_loop.moralis_scheduler_plan(
        wallets=[],
        tokens=[LINK_TOKEN],
        budget_status={
            "cu_ledger_required": True,
            "provider_polling_blocked": True,
            "normal_rps": 5,
            "current_rps": 0,
            "compute_budget": {
                "daily_budget": 900,
                "daily_reserve": 100,
                "monthly_budget": 9_000,
            },
            "persistent_cu_ledger": {
                "ledger_available": False,
                "monthly_limit_cu": 8_500,
            },
        },
        durable_rotation_available=True,
    )

    assert plan["budget_authority"] == "DURABLE_CU_LEDGER_UNAVAILABLE"
    assert plan["budget_authority_available"] is False
    assert plan["persistent_budget_authority_required"] is True
    assert plan["provider_polling_blocked"] is True
    assert plan["effective_daily_compute_unit_limit"] == 0
    assert plan["remaining_today_compute_units"] == 0
    assert plan["remaining_month_compute_units"] == 0
    assert plan["current_rps"] == 0
    assert plan["adaptive_cadence_scale"] is None
    assert plan["durable_fair_rotation"] is False
    assert plan["all_valid_configured_targets_eventually_eligible"] is False


def test_scheduler_plan_without_runtime_snapshot_never_fabricates_authority() -> None:
    plan = provider_loop.moralis_scheduler_plan(
        wallets=[],
        tokens=[LINK_TOKEN],
    )

    assert plan["budget_authority"] == "RUNTIME_BUDGET_AUTHORITY_UNBOUND"
    assert plan["budget_authority_available"] is False
    assert plan["provider_polling_blocked"] is True
    assert plan["effective_daily_compute_unit_limit"] == 0
    assert plan["normal_rps"] == 0
    assert plan["current_rps"] == 0
    assert plan["durable_fair_rotation"] is False


def test_scheduler_plan_adapts_cadence_to_live_compute_authority() -> None:
    tokens = [f"0x{index:040x}" for index in range(1, 7)]
    plan = provider_loop.moralis_scheduler_plan(
        wallets=[],
        tokens=tokens,
        budget_status=FakeLimiter().as_dict(),
        durable_rotation_available=True,
    )

    assert plan["configured_estimated_compute_units_per_day"] > 45_000
    assert plan["adaptive_cadence_scale"] > 1.0
    assert plan["estimated_compute_units_per_day"] <= 45_000
    assert plan["estimated_daily_demand_to_limit_ratio"] <= 1.0
    assert plan["durable_fair_rotation"] is True
    token_plan = next(
        row for row in plan["endpoints"] if row["endpoint_id"] == "token_transfers"
    )
    assert token_plan["effective_cadence_seconds_tier0"] > (
        token_plan["cadence_seconds_tier0"]
    )


def test_scheduler_plan_binds_remaining_authority_reset_window_and_run_budget() -> None:
    def _status(remaining_today: int) -> dict[str, Any]:
        status = FakeLimiter().as_dict()
        status["persistent_cu_ledger"] = {
            "ledger_available": True,
            "daily_limit_cu": 45_000,
            "remaining_today_cu": remaining_today,
            "monthly_limit_cu": 2_000_000,
            "remaining_month_cu": 750_000,
        }
        status["cu_ledger_required"] = True
        return status

    noon = datetime(2026, 7, 19, 12, tzinfo=UTC)
    zero = provider_loop.moralis_scheduler_plan(
        wallets=[],
        tokens=[LINK_TOKEN],
        metadata_tokens=[LINK_TOKEN],
        budget_status=_status(0),
        now_utc=noon,
    )
    below_minimum = provider_loop.moralis_scheduler_plan(
        wallets=[],
        tokens=[LINK_TOKEN],
        metadata_tokens=[LINK_TOKEN],
        budget_status=_status(9),
        now_utc=noon,
    )
    partial = provider_loop.moralis_scheduler_plan(
        wallets=[],
        tokens=[LINK_TOKEN],
        metadata_tokens=[LINK_TOKEN],
        budget_status=_status(50),
        now_utc=noon,
    )
    near_reset = provider_loop.moralis_scheduler_plan(
        wallets=[],
        tokens=[LINK_TOKEN],
        metadata_tokens=[LINK_TOKEN],
        budget_status=_status(10),
        now_utc=datetime(2026, 7, 19, 23, 59, 59, tzinfo=UTC),
    )

    assert zero["provider_polling_blocked"] is True
    assert zero["current_run_compute_unit_budget"] == 0
    assert below_minimum["provider_polling_block_reason"] == (
        "REMAINING_CU_BELOW_MINIMUM_ENDPOINT_COST"
    )
    assert below_minimum["minimum_planned_request_compute_units"] == 10
    assert partial["provider_polling_blocked"] is False
    assert partial["current_run_compute_unit_budget"] == 50
    assert partial["seconds_until_utc_day_reset"] == 43_200
    assert near_reset["provider_polling_blocked"] is False
    assert near_reset["current_run_compute_unit_budget"] == 10
    assert near_reset["seconds_until_utc_day_reset"] == 1
    assert near_reset["current_window_daily_compute_unit_allowance"] >= 10
    assert partial["steady_state_estimated_compute_units_per_day"] == (
        near_reset["steady_state_estimated_compute_units_per_day"]
    )


def test_concurrent_scheduler_lease_suppresses_provider_dispatch(monkeypatch: Any) -> None:
    redis_client = FakeRedis()
    _seed_token_map(redis_client, [("LINKUSDT", "ethereum", LINK_TOKEN)])
    redis_client.data[provider_loop._scheduler_lease_key("eth")] = "other-worker"
    client = RecordingClient()
    _patch_single_token_endpoint(monkeypatch)

    status = provider_loop.run_once(
        redis_client,
        client=client,
        chain="eth",
        wallets=[],
        tokens=[LINK_TOKEN],
        symbol="BTCUSDT",
    )

    assert client.calls == []
    assert status["request_count"] == 0
    assert status["scheduler_lease_acquired"] is False
    assert status["scheduler_run_suppressed_reason"] == (
        "CONCURRENT_SCHEDULER_RUN_ACTIVE"
    )
    assert status["durable_fair_rotation"] is False


def test_failed_cursor_write_is_not_counted_or_reported_as_durable(monkeypatch: Any) -> None:
    class CursorWriteFailRedis(FakeRedis):
        def eval(self, script: str, numkeys: int, *args: Any) -> Any:
            if "MORALIS_FENCED_CURSOR_WRITE_V1" in script:
                return 0
            return super().eval(script, numkeys, *args)

        def set(
            self,
            key: str,
            value: str,
            ex: int | None = None,
            nx: bool = False,
        ) -> bool:
            if key.startswith("v2:provider:moralis:rotation_cursor:"):
                return False
            return super().set(key, value, ex=ex, nx=nx)

    redis_client = CursorWriteFailRedis()
    _seed_token_map(redis_client, [("LINKUSDT", "ethereum", LINK_TOKEN)])
    client = RecordingClient()
    _patch_single_token_endpoint(monkeypatch)
    monkeypatch.setattr(
        provider_loop,
        "publish_moralis_result",
        lambda *args, **kwargs: {"actual_payload_present": False},
    )

    status = provider_loop.run_once(
        redis_client,
        client=client,
        chain="eth",
        wallets=[],
        tokens=[LINK_TOKEN],
        symbol="BTCUSDT",
    )

    assert status["request_count"] == 1
    assert status["rotation_cursor_advanced_count"] == 0
    assert status["rotation_state_available"] is False
    assert status["durable_fair_rotation"] is False


def test_fresh_worker_cannot_redispatch_active_durable_cadence_claim(
    monkeypatch: Any,
) -> None:
    redis_client = FakeRedis()
    _seed_token_map(redis_client, [("LINKUSDT", "ethereum", LINK_TOKEN)])
    _patch_single_token_endpoint(monkeypatch)
    monkeypatch.setattr(
        provider_loop,
        "publish_moralis_result",
        lambda *args, **kwargs: {"actual_payload_present": False},
    )
    first_client = RecordingClient()
    second_client = RecordingClient()

    first = provider_loop.run_once(
        redis_client,
        client=first_client,
        chain="eth",
        wallets=[],
        tokens=[LINK_TOKEN],
        symbol="BTCUSDT",
        scheduler_state={},
    )
    second = provider_loop.run_once(
        redis_client,
        client=second_client,
        chain="eth",
        wallets=[],
        tokens=[LINK_TOKEN],
        symbol="BTCUSDT",
        scheduler_state={},
    )

    assert first["request_count"] == 1
    assert second["request_count"] == 0
    assert second["durable_cadence_suppressed_count"] == 1
    assert second_client.calls == []
