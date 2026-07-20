from __future__ import annotations

import json

from v2.backend.app.cli.v2_coinglass_provider_loop import run_once
from v2.backend.app.cli.v2_moralis_provider_loop import run_once as run_moralis_once
from v2.backend.app.cli.v2_provider_scheduler_status import build_status
from v2.backend.app.services.coinglass_provider.models import CoinGlassResponse
from v2.backend.app.services.smart_money_wallets.models import MoralisResponse


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.data[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    def get(self, key: str):
        return self.data.get(key)


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
            "compute_budget": {
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
        )


def test_provider_scheduler_status_enforces_provider_rate_contracts() -> None:
    status = build_status(
        symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        wallets=["0xwallet1"],
        tokens=["0xtoken1"],
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


def test_moralis_loop_honors_wallet_token_cadence() -> None:
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
                    "contract_address": "0xtoken1",
                    "pollable": True,
                    "tradeable_mapping_status": "VERIFIED",
                }
            ],
        }
    )
    client = FakeMoralisClient()
    state: dict[str, float] = {}

    first = run_moralis_once(
        redis_client,
        client=client,
        chain="eth",
        wallets=["0xwallet1"],
        tokens=["0xtoken1"],
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
        wallets=["0xwallet1"],
        tokens=["0xtoken1"],
        symbol="BTCUSDT",
        scheduler_state=state,
        force=False,
        now_monotonic=160.0,
    )
    assert second["request_count"] == 0
    assert second["skipped_not_due_count"] == first_call_count

    third = run_moralis_once(
        redis_client,
        client=client,
        chain="eth",
        wallets=["0xwallet1"],
        tokens=["0xtoken1"],
        symbol="BTCUSDT",
        scheduler_state=state,
        force=False,
        now_monotonic=700.0,
    )
    assert third["request_count"] >= 3
    assert {
        endpoint
        for endpoint, _wallet, _token in client.calls[-third["request_count"]:]
    }.issuperset({
        "token_transfers",
        "token_address_transfers",
        "wallet_swaps",
    })
