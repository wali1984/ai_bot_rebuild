from __future__ import annotations

import json
from typing import Any

from v2.backend.app.cli import v2_moralis_provider_loop as moralis_provider_loop
from v2.backend.app.cli.v2_coinglass_provider_loop import (
    coinglass_scheduler_plan,
    run_once,
)
from v2.backend.app.cli.v2_moralis_provider_loop import run_once as run_moralis_once
from v2.backend.app.cli.v2_provider_scheduler_status import build_status
from v2.backend.app.services.coinglass_provider.endpoint_registry import (
    coinglass_endpoint_registry,
)
from v2.backend.app.services.coinglass_provider.models import CoinGlassResponse
from v2.backend.app.services.smart_money_wallets.models import MoralisResponse

VALID_TOKEN_ADDRESS = "0x" + ("1" * 40)
VALID_WALLET_ADDRESS = "0x" + ("2" * 40)


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.redis_time_seconds = 1_750_000_000
        self.paced_states: dict[str, dict[str, float | int]] = {}
        self.paced_reservations: dict[str, dict[str, str | int]] = {}

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
        if "MORALIS_FENCED_PACED_CU_CLAIM_V3" in script:
            if self.data.get(keys[0]) != argv[0]:
                return [-1, "0", 0, ""]
            interval = int(argv[1])
            cost = int(argv[2])
            remaining_today = int(argv[3])
            remaining_month = int(argv[4])
            day_opportunities = int(argv[5])
            month_opportunities = int(argv[6])
            day_reset = int(argv[7])
            month_reset = int(argv[8])
            reservation_id = argv[9]
            window_id = self.redis_time_seconds // interval
            if (
                self.redis_time_seconds >= day_reset
                or self.redis_time_seconds >= month_reset
            ):
                return [-4, "0", window_id, ""]
            if keys[2] in self.paced_reservations:
                return [-5, "0", window_id, ""]
            state = self.paced_states.get(keys[1])
            reset = (
                state is None
                or self.redis_time_seconds >= int(state["day_reset"])
                or self.redis_time_seconds >= int(state["month_reset"])
                or int(state["day_reset"]) != day_reset
                or int(state["month_reset"]) != month_reset
            )
            if reset:
                previous_window = window_id - 1
                credit = 0.0
            else:
                assert state is not None
                if int(state["interval"]) != interval:
                    return [-2, str(state["credit"]), window_id, ""]
                previous_window = int(state["window_id"])
                credit = float(state["credit"])
            earned = min(
                remaining_today / day_opportunities,
                remaining_month / month_opportunities,
            )
            earned_for_elapsed = earned
            if not reset:
                assert state is not None
                earned_for_elapsed = min(float(state["earned"]), earned)
            bound = min(remaining_today, remaining_month)
            credit = min(
                bound,
                credit + (window_id - previous_window) * earned_for_elapsed,
            )
            admitted = credit + 1e-9 >= cost
            if admitted:
                credit -= cost
            self.paced_states[keys[1]] = {
                "window_id": window_id,
                "credit": credit,
                "interval": interval,
                "day_reset": day_reset,
                "month_reset": month_reset,
                "bound": bound,
                "earned": earned,
            }
            if admitted:
                self.paced_reservations[keys[2]] = {
                    "reservation_id": reservation_id,
                    "lease_key": keys[0],
                    "lease_token": argv[0],
                    "window_id": window_id,
                    "cost": cost,
                    "credit_key": keys[1],
                    "day_reset": day_reset,
                    "month_reset": month_reset,
                }
            return [
                int(admitted),
                str(credit),
                window_id,
                reservation_id if admitted else "",
            ]
        if "MORALIS_FENCED_PACED_CU_RELEASE_V3" in script:
            if self.data.get(keys[0]) != argv[0]:
                return 0
            reservation = self.paced_reservations.get(keys[2])
            state = self.paced_states.get(keys[1])
            if (
                reservation is None
                or state is None
                or reservation["reservation_id"] != argv[1]
                or reservation["lease_key"] != keys[0]
                or reservation["lease_token"] != argv[0]
                or reservation["credit_key"] != keys[1]
                or int(reservation["window_id"]) != int(argv[2])
                or int(reservation["cost"]) != int(argv[3])
                or int(reservation["day_reset"]) != int(state["day_reset"])
                or int(reservation["month_reset"]) != int(state["month_reset"])
                or int(state["window_id"]) != int(argv[2])
            ):
                return 0
            cost = int(argv[3])
            state["credit"] = min(
                float(state["bound"]),
                float(state["credit"]) + cost,
            )
            del self.paced_reservations[keys[2]]
            return 1
        if "MORALIS_FENCED_PACED_CU_FINALIZE_V1" in script:
            if self.data.get(keys[0]) != argv[0]:
                return 0
            reservation = self.paced_reservations.get(keys[2])
            state = self.paced_states.get(keys[1])
            if (
                reservation is None
                or state is None
                or reservation["reservation_id"] != argv[1]
                or reservation["lease_key"] != keys[0]
                or reservation["lease_token"] != argv[0]
                or reservation["credit_key"] != keys[1]
                or int(reservation["window_id"]) != int(argv[2])
                or int(reservation["cost"]) != int(argv[3])
                or int(reservation["day_reset"]) != int(state["day_reset"])
                or int(reservation["month_reset"]) != int(state["month_reset"])
            ):
                return 0
            del self.paced_reservations[keys[2]]
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
        if spec.endpoint_id == "funding_rate":
            payload = {
                "data": [
                    {
                        "symbol": coin,
                        "stablecoin_margin_list": [
                            {
                                "exchange": "Binance",
                                "funding_rate": funding_rate,
                            }
                        ],
                    }
                    for coin, funding_rate in (
                        ("BTC", 0.01),
                        ("ETH", 0.02),
                        ("SOL", 0.03),
                    )
                ]
            }
        else:
            payload = {
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
            }
        return CoinGlassResponse(
            spec.endpoint_id,
            symbol,
            200,
            payload,
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

    def get(
        self,
        spec,
        *,
        chain: str,
        wallet: str | None = None,
        token: str | None = None,
        symbol: str | None = None,
    ):
        self.calls.append((spec.endpoint_id, wallet, token))
        payload = {
            "result": [
                {
                    "direction": "out",
                    "value_usd": 1200,
                    "block_timestamp": "2026-07-08T12:00:00Z",
                }
            ]
        }
        if spec.endpoint_id in {"wallet_swaps", "token_swaps"}:
            payload = {
                "result": [
                    {
                        "side": "buy",
                        "total_value_usd": 800,
                        "block_timestamp": "2026-07-08T12:00:00Z",
                    }
                ]
            }
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
    assert third["request_count"] == 0

    fourth = run_once(
        redis_client,
        client=client,
        symbols=["BTCUSDT"],
        scheduler_state=state,
        force=False,
        now_monotonic=400.0,
    )
    assert fourth["request_count"] == first_call_count
    assert {
        endpoint for endpoint, _symbol in client.calls[-first_call_count:]
    }.issuperset({
        "long_short_ratio",
        "liquidation_orders",
        "trades",
        "orderbook_l2_l3",
    })


def test_coinglass_funding_fetches_once_and_fans_out_to_due_symbols() -> None:
    redis_client = FakeRedis()
    client = FakeCoinGlassClient()
    state: dict[str, float] = {}
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    disabled = frozenset(
        spec.endpoint_id
        for spec in coinglass_endpoint_registry()
        if spec.endpoint_id != "funding_rate"
    )

    report = run_once(
        redis_client,
        client=client,
        symbols=symbols,
        scheduler_state=state,
        force=False,
        now_monotonic=100.0,
        disabled_endpoints=disabled,
    )

    assert client.calls == [("funding_rate", None)]
    assert report["request_count"] == 1
    assert report["result_count"] == 3
    assert report["actual_payload_results"] == 3
    assert state == {
        "funding_rate:BTCUSDT": 100.0,
        "funding_rate:ETHUSDT": 100.0,
        "funding_rate:SOLUSDT": 100.0,
    }
    expected_rates = {
        "BTCUSDT": 0.0001,
        "ETHUSDT": 0.0002,
        "SOLUSDT": 0.0003,
    }
    for output_symbol, expected_rate in expected_rates.items():
        raw = json.loads(redis_client.data[f"v2:coinglass:funding:{output_symbol}"])
        assert raw["features"]["coinglass_funding_rate"] == expected_rate

    plan = coinglass_scheduler_plan(symbols)
    endpoint_rows = {row["endpoint_id"]: row for row in plan["endpoints"]}
    assert endpoint_rows["funding_rate"]["response_scope"] == "all_symbols"
    assert endpoint_rows["funding_rate"]["estimated_requests_per_cycle"] == 1
    assert endpoint_rows["market_snapshot"]["response_scope"] == "per_symbol"
    assert endpoint_rows["market_snapshot"]["estimated_requests_per_cycle"] == 3


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
    assert first_call_count > 0
    assert first["current_run_admitted_compute_units"] <= (
        first["schedule_plan"]["earned_compute_units_per_window"]
    )
    assert first["paced_cu_admission_state_available"] is True

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
    assert len(client.calls) == first_call_count
    assert second["skipped_not_due_count"] >= 1
    assert second["scheduler_run_suppressed_reason"] in {
        None,
        "PACED_CU_CREDIT_ACCUMULATING_FOR_NEXT_DUE_JOB",
    }

    # The production Redis lease keys expire by their adaptive cadence TTL.
    # This in-memory fake has no clock/expiry engine, so emulate that expiry
    # before advancing the scheduler's monotonic clock.
    for key in list(redis_client.data):
        if key.startswith("v2:provider:moralis:cadence_claim:"):
            redis_client.data.pop(key)
    redis_client.redis_time_seconds += 300
    calls_before_third = len(client.calls)

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
    assert third["request_count"] > 0
    assert len(client.calls) == calls_before_third + third["request_count"]
