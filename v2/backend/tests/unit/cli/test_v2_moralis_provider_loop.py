from __future__ import annotations

import json
from typing import Any

from v2.backend.app.cli.v2_moralis_provider_loop import _loop_log_report, run_once
from v2.backend.app.cli.v2_moralis_token_map_bootstrap import build_phase0_state
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

    def exists(self, key: str) -> int:
        return 1 if key in self.data else 0

    def eval(self, script: str, numkeys: int, *args: Any) -> Any:
        keys = [str(item) for item in args[:numkeys]]
        argv = [str(item) for item in args[numkeys:]]
        if "MORALIS_AGGREGATE_CAS_V1" in script:
            current = self.data.get(keys[0])
            if argv[0] == "0":
                if current is not None:
                    return 0
            elif current != argv[1]:
                return 0
            self.data[keys[0]] = argv[2]
            self.ttls[keys[0]] = int(argv[3])
            return 1
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
    def __init__(self, redis_client: FakeRedis | None = None) -> None:
        self.cu = FakePersistentCuBudget(redis_client) if redis_client is not None else None

    def as_dict(self) -> dict[str, object]:
        return {
            "current_rps": 5,
            "normal_rps": 5,
            "catchup_rps": 10,
            "hard_rps": 30,
            "distributed_rps_guard": True,
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


class FakePersistentCuBudget:
    def __init__(self, redis_client: FakeRedis) -> None:
        self.redis_client = redis_client

    def publish_status(
        self,
        *,
        extra: dict[str, object] | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": "moralis_cu_budget_status_v2",
            "ledger_available": True,
            **(extra or {}),
            "status_publish_succeeded": True,
        }
        self.redis_client.set(
            "v2:provider:moralis:cu_budget_status",
            json.dumps(payload),
            ex=6 * 3_600,
        )
        return payload


class FakeClient:
    def __init__(self, redis_client: FakeRedis | None = None) -> None:
        self.limiter = FakeLimiter(redis_client)
        self.calls: list[str] = []

    def get(
        self,
        spec,
        *,
        chain: str,
        wallet: str | None = None,
        token: str | None = None,
        symbol: str | None = None,
    ):
        self.calls.append(spec.endpoint_id)
        return MoralisResponse(
            spec.endpoint_id,
            chain,
            wallet,
            token,
            symbol,
            200,
            {
                "result": [
                    {
                        "direction": "out",
                        "value_usd": 100,
                        "block_timestamp": "2026-07-08T12:00:00Z",
                    }
                ]
            },
            request_dispatched=True,
        )


def test_loop_log_report_is_bounded_and_keeps_operational_truth() -> None:
    report = {
        "generated_utc": "2026-07-20T11:03:24Z",
        "status": "READY",
        "bootstrap_status": "WATCHLIST_READY",
        "chain": "eth",
        "token_count": 6,
        "token_map_count": 6,
        "wallet_watchlist_count": 0,
        "request_count": 2,
        "result_count": 2,
        "actual_payload_results": 0,
        "dispatched_request_count": 2,
        "skipped_not_due_count": 28,
        "scheduler_run_suppressed_reason": None,
        "durable_cu_budget_status_published": True,
        "durable_fair_rotation": True,
        "schedule_plan": {
            "budget_authority": "DURABLE_CU_LEDGER",
            "budget_authority_available": True,
            "remaining_today_compute_units": 31_440,
            "estimated_compute_units_per_day": 44_520,
            "effective_daily_compute_unit_limit": 45_000,
            "endpoints": [{"payload": "x" * 100_000}] * 20,
        },
        "registry": {"payload": "y" * 1_000_000},
        "skipped_not_due": [{"payload": "z" * 100_000}] * 20,
        "api_key": "must-not-reach-console",
    }

    compact = _loop_log_report(report)
    encoded = json.dumps(compact, sort_keys=True, separators=(",", ":"))

    assert compact["schema_version"] == "moralis_provider_loop_log_v1"
    assert compact["status"] == "READY"
    assert compact["actual_payload_results"] == 0
    assert compact["budget_authority"] == "DURABLE_CU_LEDGER"
    assert compact["remaining_today_compute_units"] == 31_440
    assert compact["full_scheduler_report_console_omitted"] is True
    assert compact["raw_key_exposed"] is False
    assert compact["places_real_order"] is False
    assert compact["routes_to_live"] is False
    assert "registry" not in compact
    assert "skipped_not_due" not in compact
    assert "api_key" not in compact
    assert len(encoded.encode("utf-8")) < 4_096


def test_moralis_loop_no_watchlist_publishes_gray_and_makes_no_requests(monkeypatch) -> None:
    monkeypatch.setenv("MORALIS_API_KEY", "secret")
    redis_client = FakeRedis()
    client = FakeClient(redis_client)
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
    assert feature_payload["schema_version"] == "moralis_feature_bridge_v2"
    assert feature_payload["required_feature_count"] == 0
    assert feature_payload["optional_feature_count"] == 7
    assert feature_payload["available_at"] is None
    assert feature_payload["publication_authority"] is False
    assert feature_payload["heartbeat_only"] is True
    assert feature_payload["dashboard_color"] == "GRAY"
    assert feature_payload["missing_feature_flags"]
    feature_status = json.loads(redis_client.data["v2:provider:moralis:feature_bridge_status"])
    assert feature_status["token_map_count"] == 0
    assert feature_status["wallet_watchlist_count"] == 0
    cu_status = json.loads(redis_client.data["v2:provider:moralis:cu_budget_status"])
    assert cu_status["schema_version"] == "moralis_cu_budget_status_v2"
    assert cu_status["ledger_available"] is True
    assert cu_status["status_key"] == "v2:provider:moralis:cu_budget_status"
    assert status["durable_cu_budget_status_published"] is True


def test_moralis_loop_operator_lists_still_schedule_without_every_symbol_minute() -> None:
    redis_client = FakeRedis()
    client = FakeClient(redis_client)
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
    assert status["durable_cu_budget_status_published"] is True
    assert redis_client.ttls["v2:provider:moralis:cu_budget_status"] == 6 * 3_600
    assert client.calls


def test_phase0_state_reports_missing_lists_without_key_exposure() -> None:
    redis_client = FakeRedis()
    payload = build_phase0_state(redis_client, env={"MORALIS_API_KEY": "secret"})
    assert payload["moralis_api_key_present"] is True
    assert payload["moralis_token_map_count"] == 0
    assert payload["moralis_wallet_watchlist_count"] == 0
    assert payload["dashboard_color"] == "GRAY"
    assert payload["raw_key_exposed"] is False
