from __future__ import annotations

import json
from typing import Any

from v2.backend.app.cli import v2_moralis_provider_loop as moralis_provider_loop
from v2.backend.app.cli.v2_coinglass_provider_loop import run_once
from v2.backend.app.cli.v2_moralis_provider_loop import run_once as run_moralis_once
from v2.backend.app.cli.v2_provider_scheduler_status import build_status
from v2.backend.app.services.coinglass_provider.models import CoinGlassResponse
from v2.backend.app.services.smart_money_wallets.models import MoralisResponse

VALID_TOKEN_ADDRESS = "0x" + ("1" * 40)
VALID_WALLET_ADDRESS = "0x" + ("2" * 40)


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def set(
        self,
        key: str,
        value: str,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool:
        if nx and key in self.data:
            return False
        self.data[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    def delete(self, key: str) -> int:
        return int(self.data.pop(key, None) is not None)

    def get(self, key: str):
        return self.data.get(key)

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
    def as_dict(self) -> dict[str, object]:
        return {"requests_per_minute": 210, "tokens_available": 210}


class FakeCoinGlassClient:
    def __init__(self) -> None:
        self.limiter = FakeLimiter()
        self.calls: list[tuple[str, str | None]] = []

    def get(self, spec, *, symbol: str | None = None):
        self.calls.append((spec.endpoint_id, symbol))
        return CoinGlassResponse(
            spec.endpoint_id,
            symbol,
            200,
            {
                "data": [
                    {
                        "time": 1783512000000,
                        "fundingRate": 0.0002,
                        "openInterestUsd": 1234567,
                        "longAccount": 0.55,
                        "shortAccount": 0.45,
                        "longShortRatio": 1.2,
                        "shortLiquidationUsd": 1000,
                        "longLiquidationUsd": 500,
                        "nearest_above_usd": 70000,
                        "nearest_below_usd": 60000,
                        "buy_usd": 900,
                        "sell_usd": 300,
                        "bid_usd": 10000,
                        "ask_usd": 8000,
                    }
                ]
            },
        )


class FakeMoralisLimiter:
    def as_dict(self) -> dict[str, object]:
        return {
            "current_rps": 5,
            "normal_rps": 5,
            "catchup_rps": 10,
            "hard_rps": 30,
            "cu_ledger_required": False,
            "provider_polling_blocked": False,
            "compute_budget": {
                "daily_budget": 55_000,
                "daily_reserve": 10_000,
                "monthly_budget": 2_000_000,
                "used_today": 0,
                "used_month": 0,
                "remaining_today": 45_000,
                "remaining_month": 2_000_000,
            },
        }


class FakeMoralisClient:
    def __init__(self) -> None:
        self.limiter = FakeMoralisLimiter()
        self.calls: list[tuple[str, str | None, str | None]] = []

    def get(self, spec, *, chain: str, wallet: str | None = None, token: str | None = None, symbol: str | None = None):
        self.calls.append((spec.endpoint_id, wallet, token))
        payload = {"result": [{"direction": "out", "value_usd": 1200, "block_timestamp": "2026-07-08T12:00:00Z"}]}
        if spec.endpoint_id in {"wallet_swaps", "token_swaps"}:
            payload = {"result": [{"side": "buy", "total_value_usd": 800, "block_timestamp": "2026-07-08T12:00:00Z"}]}
        if spec.endpoint_id == "token_holders":
            payload = {"result": [{"owner_address": "0xabc"}]}
        return MoralisResponse(
            spec.endpoint_id,
            chain,
            wallet,
            token,
            symbol,
            200,
            payload,
            request_dispatched=True,
        )


def test_provider_scheduler_status_enforces_provider_rate_contracts() -> None:
    status = build_status(
        symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        wallets=[VALID_WALLET_ADDRESS],
        tokens=[VALID_TOKEN_ADDRESS],
    )
    assert status["coinglass_schedule_plan"]["scheduled_request_budget_per_minute"] <= 285
    assert status["moralis_schedule_plan"]["does_not_poll_every_symbol_every_minute"] is True
    assert status["heartbeat_only_green_allowed"] is False
    assert status["raw_key_exposed"] is False


def test_coinglass_loop_honors_endpoint_cadence() -> None:
    redis_client = FakeRedis()
    client = FakeCoinGlassClient()
    state: dict[str, float] = {}

    first = run_once(
        redis_client,
        client=client,
        symbols=["BTCUSDT"],
        scheduler_state=state,
        force=False,
        now_monotonic=100.0,
    )
    first_call_count = len(client.calls)
    assert first["request_count"] == first_call_count
    assert first_call_count > 0

    second = run_once(
        redis_client,
        client=client,
        symbols=["BTCUSDT"],
        scheduler_state=state,
        force=False,
        now_monotonic=110.0,
    )
    assert second["request_count"] == 0
    assert second["skipped_not_due_count"] == first_call_count

    third = run_once(
        redis_client,
        client=client,
        symbols=["BTCUSDT"],
        scheduler_state=state,
        force=False,
        now_monotonic=130.0,
    )
    assert third["request_count"] == 3
    assert {endpoint for endpoint, _symbol in client.calls[-3:]} == {
        "liquidation_orders",
        "trades",
        "orderbook_l2_l3",
    }


def test_moralis_loop_honors_wallet_token_cadence(monkeypatch: Any) -> None:
    redis_client = FakeRedis()
    redis_client.data["v2:moralis:token_map_status"] = json.dumps(
        {"token_map_count": 1, "symbols": ["BTCUSDT"]}
    )
    redis_client.data["v2:moralis:token_map:BTCUSDT"] = json.dumps(
        {
            "symbol": "BTCUSDT",
            "contracts": [
                {
                    "chain": "ethereum",
                    "contract_address": VALID_TOKEN_ADDRESS,
                    "pollable": True,
                    "tradeable_mapping_status": "VERIFIED",
                }
            ],
        }
    )
    fixture_rows = [
        {
            "symbol": "BTCUSDT",
            "chain": "ethereum",
            "token": VALID_TOKEN_ADDRESS,
        }
    ]
    monkeypatch.setattr(
        moralis_provider_loop,
        "read_pollable_tokens",
        lambda *_args, **_kwargs: fixture_rows,
    )
    monkeypatch.setattr(
        moralis_provider_loop,
        "read_metadata_validation_tokens",
        lambda *_args, **_kwargs: fixture_rows,
    )
    client = FakeMoralisClient()
    state: dict[str, float] = {}

    first = run_moralis_once(
        redis_client,
        client=client,
        chain="eth",
        wallets=[VALID_WALLET_ADDRESS],
        tokens=[VALID_TOKEN_ADDRESS],
        symbol="BTCUSDT",
        scheduler_state=state,
        force=False,
        now_monotonic=100.0,
    )
    first_call_count = len(client.calls)
    assert first["request_count"] == first_call_count
    assert first_call_count > 6

    second = run_moralis_once(
        redis_client,
        client=client,
        chain="eth",
        wallets=[VALID_WALLET_ADDRESS],
        tokens=[VALID_TOKEN_ADDRESS],
        symbol="BTCUSDT",
        scheduler_state=state,
        force=False,
        now_monotonic=160.0,
    )
    assert second["request_count"] == 0
    assert second["skipped_not_due_count"] == first_call_count

    # The production Redis lease keys expire by their adaptive cadence TTL.
    # This in-memory fake has no clock/expiry engine, so emulate that expiry
    # before advancing the scheduler's monotonic clock.
    for key in list(redis_client.data):
        if key.startswith("v2:provider:moralis:cadence_claim:"):
            redis_client.data.pop(key)

    third = run_moralis_once(
        redis_client,
        client=client,
        chain="eth",
        wallets=[VALID_WALLET_ADDRESS],
        tokens=[VALID_TOKEN_ADDRESS],
        symbol="BTCUSDT",
        scheduler_state=state,
        force=False,
        now_monotonic=10_000.0,
    )
    assert third["request_count"] >= 3
    assert {
        endpoint
        for endpoint, _wallet, _token in client.calls[-third["request_count"]:]
    }.issuperset({
        "token_transfers",
        "wallet_swaps",
    })
