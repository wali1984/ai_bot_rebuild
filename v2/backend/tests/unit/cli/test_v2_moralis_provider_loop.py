from __future__ import annotations

import json
from typing import Any

from v2.backend.app.cli.v2_moralis_provider_loop import run_once
from v2.backend.app.cli.v2_moralis_token_map_bootstrap import build_phase0_state
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

    def exists(self, key: str) -> int:
        return 1 if key in self.data else 0

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
            request_dispatched=True,
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
    assert status["canonical_token_transfer_transport_owner"] is False
    health = json.loads(redis_client.data["v2:provider:moralis:health"])
    assert health["status"] == "CONFIGURED_NO_WATCHLIST"
    assert health["dashboard_color"] == "GRAY"
    assert health["core_system_blocked"] is False
    assert health["feature_bridge_ready"] is False
    assert health["actual_payload_present"] is False
    assert health["heartbeat_only"] is True
    assert health["missing_mask_true"] is True
    feature_payload = json.loads(redis_client.data["v2:features:moralis:BTCUSDT:1m"])
    assert feature_payload["schema_version"] == "moralis_feature_bridge_v1"
    assert feature_payload["heartbeat_only"] is True
    assert feature_payload["dashboard_color"] == "GRAY"
    assert feature_payload["missing_feature_flags"]
    feature_status = json.loads(redis_client.data["v2:provider:moralis:feature_bridge_status"])
    assert feature_status["token_map_count"] == 0
    assert feature_status["wallet_watchlist_count"] == 0


def test_moralis_loop_operator_lists_still_schedule_without_every_symbol_minute() -> None:
    redis_client = FakeRedis()
    client = FakeClient()
    status = run_once(
        redis_client,
        client=client,
        chain="eth",
        wallets=[VALID_WALLET_ADDRESS],
        tokens=[VALID_TOKEN_ADDRESS],
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
