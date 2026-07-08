from __future__ import annotations

import json

from v2.backend.app.cli.v2_moralis_provider_loop import run_once
from v2.backend.app.cli.v2_moralis_token_map_bootstrap import build_phase0_state
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

    def exists(self, key: str) -> int:
        return 1 if key in self.data else 0


class FakeLimiter:
    def as_dict(self) -> dict[str, object]:
        return {
            "current_rps": 5,
            "compute_budget": {
                "used_today": 0,
                "used_month": 0,
                "remaining_today": 45_000,
                "remaining_month": 2_000_000,
            },
            "raw_key_exposed": False,
            "core_system_blocked": False,
        }


class FakeClient:
    def __init__(self) -> None:
        self.limiter = FakeLimiter()
        self.calls: list[str] = []

    def get(self, spec, *, chain: str, wallet: str | None = None, token: str | None = None, symbol: str | None = None):
        self.calls.append(spec.endpoint_id)
        return MoralisResponse(
            spec.endpoint_id,
            chain,
            wallet,
            token,
            symbol,
            200,
            {"result": [{"direction": "out", "value_usd": 100, "block_timestamp": "2026-07-08T12:00:00Z"}]},
        )


def test_moralis_loop_no_watchlist_publishes_gray_and_makes_no_requests(monkeypatch) -> None:
    monkeypatch.setenv("MORALIS_API_KEY", "secret")
    redis_client = FakeRedis()
    client = FakeClient()
    status = run_once(
        redis_client,
        client=client,
        chain="eth",
        wallets=[],
        tokens=[],
        symbol="BTCUSDT",
        scheduler_state={},
        force=False,
        now_monotonic=100.0,
    )

    assert client.calls == []
    assert status["status"] == "CONFIGURED_NO_WATCHLIST"
    assert status["request_count"] == 0
    health = json.loads(redis_client.data["v2:provider:moralis:health"])
    assert health["status"] == "CONFIGURED_NO_WATCHLIST"
    assert health["dashboard_color"] == "GRAY"
    assert health["core_system_blocked"] is False


def test_moralis_loop_operator_lists_still_schedule_without_every_symbol_minute() -> None:
    redis_client = FakeRedis()
    client = FakeClient()
    status = run_once(
        redis_client,
        client=client,
        chain="eth",
        wallets=["0xwallet"],
        tokens=["0xtoken"],
        symbol="BTCUSDT",
        scheduler_state={},
        force=False,
        now_monotonic=100.0,
    )

    assert status["request_count"] > 0
    assert status["does_not_poll_every_symbol_every_minute"] is True
    assert status["core_system_blocked"] is False
    assert client.calls


def test_phase0_state_reports_missing_lists_without_key_exposure() -> None:
    redis_client = FakeRedis()
    payload = build_phase0_state(redis_client, env={"MORALIS_API_KEY": "secret"})
    assert payload["moralis_api_key_present"] is True
    assert payload["moralis_token_map_count"] == 0
    assert payload["moralis_wallet_watchlist_count"] == 0
    assert payload["dashboard_color"] == "GRAY"
    assert payload["raw_key_exposed"] is False
