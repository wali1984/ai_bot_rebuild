from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from v2.backend.app.cli import v2_moralis_provider_loop as provider_loop
from v2.backend.app.services.smart_money_wallets.endpoint_registry import (
    MoralisEndpointSpec,
)
from v2.backend.app.services.smart_money_wallets.models import (
    MORALIS_RAW_RESPONSE_BYTES_SCOPE,
    MoralisResponse,
)
from v2.backend.app.services.smart_money_wallets.wallet_watchlist import (
    load_wallet_watchlist_seed,
)

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

WALLET_SPEC = MoralisEndpointSpec(
    endpoint_id="wallet_transactions",
    group="wallet_transactions",
    path_template="/wallets/{wallet}/history?chain={chain}",
    purpose="paced wallet rotation test",
    priority="HIGH",
    cu_cost=50,
    cadence_seconds_tier0=600,
    cadence_seconds_tier1=600,
    cadence_seconds_full_watchlist=600,
    ttl_seconds=3600,
    feature_outputs=("moralis_wallet_transaction_count",),
    requires_wallet=True,
)


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.redis_time_seconds = 1_750_000_000
        self.paced_states: dict[str, dict[str, float | int]] = {}
        self.paced_reservations: dict[str, dict[str, str | int]] = {}

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


class ExpiringFakeRedis(FakeRedis):
    def __init__(self) -> None:
        super().__init__()
        self.expires_at: dict[str, int] = {}

    def _purge(self, key: str) -> None:
        expires_at = self.expires_at.get(key)
        if expires_at is not None and self.redis_time_seconds >= expires_at:
            self.data.pop(key, None)
            self.expires_at.pop(key, None)

    def get(self, key: str) -> str | None:
        self._purge(key)
        return super().get(key)

    def set(
        self,
        key: str,
        value: str,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool:
        self._purge(key)
        written = super().set(key, value, ex=ex, nx=nx)
        if written and ex is not None:
            self.expires_at[key] = self.redis_time_seconds + int(ex)
        return written

    def delete(self, key: str) -> int:
        self.expires_at.pop(key, None)
        return super().delete(key)

    def eval(self, script: str, numkeys: int, *args: Any) -> Any:
        keys = [str(item) for item in args[:numkeys]]
        argv = [str(item) for item in args[numkeys:]]
        for key in keys:
            self._purge(key)
        result = super().eval(script, numkeys, *args)
        if (
            "MORALIS_FENCED_CADENCE_CLAIM_V1" in script
            and isinstance(result, list)
            and result[0] == 1
        ):
            self.expires_at[keys[1]] = self.redis_time_seconds + int(argv[2])
        return result


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


class FixedWindowLimiter:
    cu = None

    def __init__(
        self,
        *,
        remaining_today_cu: int = 50,
        remaining_month_cu: int = 1_000_000,
    ) -> None:
        self.remaining_today_cu = remaining_today_cu
        self.remaining_month_cu = remaining_month_cu
        self.debited_cu = 0

    def debit(self, compute_units: int) -> None:
        cost = int(compute_units)
        self.remaining_today_cu -= cost
        self.remaining_month_cu -= cost
        self.debited_cu += cost

    def as_dict(self) -> dict[str, Any]:
        return {
            "normal_rps": 5,
            "catchup_rps": 10,
            "hard_rps": 30,
            "current_rps": 5,
            "cu_ledger_required": True,
            "provider_polling_blocked": False,
            "compute_budget": {
                "daily_budget": 55_000,
                "daily_reserve": 10_000,
                "monthly_budget": 2_000_000,
            },
            "persistent_cu_ledger": {
                "ledger_available": True,
                "daily_limit_cu": 45_000,
                "remaining_today_cu": self.remaining_today_cu,
                "monthly_limit_cu": 2_000_000,
                "remaining_month_cu": self.remaining_month_cu,
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


class DebitTrackingClient(RecordingClient):
    def __init__(self, limiter: FixedWindowLimiter) -> None:
        super().__init__()
        self.limiter = limiter

    def get(
        self,
        spec: MoralisEndpointSpec,
        *,
        chain: str,
        wallet: str | None = None,
        token: str | None = None,
        symbol: str | None = None,
    ) -> MoralisResponse:
        response = super().get(
            spec,
            chain=chain,
            wallet=wallet,
            token=token,
            symbol=symbol,
        )
        self.limiter.debit(spec.cu_cost)
        return response


class EvidenceRecordingClient(RecordingClient):
    def get(
        self,
        spec: MoralisEndpointSpec,
        *,
        chain: str,
        wallet: str | None = None,
        token: str | None = None,
        symbol: str | None = None,
    ) -> MoralisResponse:
        response = super().get(
            spec,
            chain=chain,
            wallet=wallet,
            token=token,
            symbol=symbol,
        )
        raw = b'{"result":[]}'
        return replace(
            response,
            raw_response_bytes=raw,
            raw_response_sha256=hashlib.sha256(raw).hexdigest(),
            raw_response_byte_count=len(raw),
            raw_response_bytes_scope=MORALIS_RAW_RESPONSE_BYTES_SCOPE,
            transport_started_at="2026-07-20T12:00:00.000001Z",
            observed_at="2026-07-20T12:00:00.000002Z",
            ingested_at="2026-07-20T12:00:00.000003Z",
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


def _patch_single_wallet_endpoint(monkeypatch: Any) -> None:
    monkeypatch.setattr(provider_loop, "moralis_endpoint_registry", lambda: (WALLET_SPEC,))
    monkeypatch.setattr(
        provider_loop,
        "publish_moralis_feature_payload",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        provider_loop,
        "publish_moralis_result",
        lambda *args, **kwargs: {"actual_payload_present": False},
    )


def test_poll_job_priority_is_t0_then_token_bootstrap_then_t1() -> None:
    t0_wallet = "0x" + ("1" * 40)
    t1_wallet = "0x" + ("2" * 40)
    jobs = [
        (WALLET_SPEC, 1, t1_wallet, None),
        (TOKEN_SPEC, 0, None, LINK_TOKEN),
        (WALLET_SPEC, 0, t0_wallet, None),
    ]

    ordered = sorted(
        jobs,
        key=lambda job: provider_loop._poll_job_priority_key(
            job,
            wallet_tiers={t0_wallet: "T0", t1_wallet: "T1"},
        ),
    )

    assert [(job[0].endpoint_id, job[2], job[3]) for job in ordered] == [
        ("wallet_transactions", t0_wallet, None),
        ("token_transfers", None, LINK_TOKEN),
        ("wallet_transactions", t1_wallet, None),
    ]


def test_legacy_or_mismatched_cursor_starts_new_tier_first_universe_at_t0() -> None:
    redis_client = FakeRedis()
    t0_wallet = "0x" + ("1" * 40)
    t1_wallet = "0x" + ("2" * 40)
    jobs = [
        (WALLET_SPEC, 0, t0_wallet, None),
        (TOKEN_SPEC, 0, None, LINK_TOKEN),
        (WALLET_SPEC, 1, t1_wallet, None),
    ]
    legacy_token_cursor = provider_loop._poll_job_id(
        TOKEN_SPEC,
        chain="eth",
        wallet=None,
        token=LINK_TOKEN,
        context_symbol="BTCUSDT",
    )
    legacy_key = provider_loop.LEGACY_ROTATION_CURSOR_KEY.format(chain="eth")
    redis_client.data[legacy_key] = legacy_token_cursor

    ordered, available, universe_digest = provider_loop._rotate_poll_jobs(
        redis_client,
        chain="eth",
        jobs=jobs,
        context_symbol="BTCUSDT",
    )

    assert available is True
    assert ordered == jobs
    assert ordered[0][2] == t0_wallet
    assert redis_client.data[legacy_key] == legacy_token_cursor
    v2_key = provider_loop._rotation_cursor_key("eth")
    assert v2_key not in redis_client.data

    redis_client.data[v2_key] = f"{'0' * 64}:{legacy_token_cursor}"
    mismatched, mismatch_available, new_digest = provider_loop._rotate_poll_jobs(
        redis_client,
        chain="eth",
        jobs=jobs,
        context_symbol="BTCUSDT",
    )

    assert mismatch_available is True
    assert new_digest == universe_digest
    assert mismatched == jobs
    assert mismatched[0][2] == t0_wallet


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
    client = EvidenceRecordingClient()
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
    assert published[0]["raw_response_bytes"] == b'{"result":[]}'
    assert published[0]["raw_response_sha256"] == hashlib.sha256(b'{"result":[]}').hexdigest()
    assert published[0]["raw_response_byte_count"] == len(b'{"result":[]}')
    assert published[0]["raw_response_bytes_scope"] == MORALIS_RAW_RESPONSE_BYTES_SCOPE
    assert published[0]["transport_started_at"] == "2026-07-20T12:00:00.000001Z"
    assert published[0]["observed_at"] == "2026-07-20T12:00:00.000002Z"
    assert published[0]["ingested_at"] == "2026-07-20T12:00:00.000003Z"
    generated_at = datetime.fromisoformat(
        str(published[0]["generated_at"]).replace("Z", "+00:00")
    )
    assert generated_at.tzinfo is not None
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
    assert plan["adaptive_overload_ratio_applied_to_target_cadence"] is False
    assert plan["target_cadence_policy"] == (
        "SOURCE_TIER_BASE_PLUS_DURABLE_FAIR_PACED_CU_V1"
    )
    assert plan["durable_fair_rotation"] is True
    token_plan = next(
        row for row in plan["endpoints"] if row["endpoint_id"] == "token_transfers"
    )
    assert token_plan["effective_cadence_seconds_tier0"] == (
        token_plan["cadence_seconds_tier0"]
    )


def test_270_candidate_live_plan_preserves_tiers_and_fair_paces_full_demand() -> None:
    rows = load_wallet_watchlist_seed(
        observed_at=datetime(2026, 7, 21, 10, 50, tzinfo=UTC)
    )
    eth_rows = [row for row in rows if row["chain"] == "eth"]
    wallets = [str(row["address"]) for row in eth_rows]
    wallet_tiers = {str(row["address"]): str(row["tier"]) for row in eth_rows}
    tokens = [f"0x{index:040x}" for index in range(1, 7)]
    budget_status = FixedWindowLimiter(
        remaining_today_cu=26_130,
        remaining_month_cu=1_945_510,
    ).as_dict()

    plan = provider_loop.moralis_scheduler_plan(
        wallets=wallets,
        tokens=tokens,
        metadata_tokens=tokens,
        budget_status=budget_status,
        chain="eth",
        wallet_tiers=wallet_tiers,
        scheduler_interval_seconds=300,
        now_utc=datetime(2026, 7, 21, 10, 50, tzinfo=UTC),
        durable_rotation_available=True,
    )

    assert len(rows) == 270
    assert len(eth_rows) == 239
    assert sum(row["chain"] == "optimism" for row in rows) == 17
    assert sum(row["chain"] == "arbitrum" for row in rows) == 14
    assert sum(row["tier"] == "T0" for row in eth_rows) == 18
    assert sum(row["tier"] == "T1" for row in eth_rows) == 221
    assert plan["configured_target_count"] == 1_464
    assert plan["estimated_compute_units_per_cycle"] == 151_830
    assert plan["daily_admission_opportunity_count"] == 158
    assert plan["daily_paced_run_compute_unit_allowance"] == 165
    assert plan["monthly_paced_run_compute_unit_allowance"] == 640
    assert plan["current_run_compute_unit_budget"] == 165
    assert plan["current_run_compute_unit_budget"] < plan[
        "estimated_compute_units_per_cycle"
    ]
    assert plan["adaptive_overload_ratio"] == pytest.approx(92.0133333333)
    assert plan["adaptive_overload_ratio"] < 100
    assert plan["adaptive_overload_ratio_applied_to_target_cadence"] is False
    assert plan["estimated_compute_units_per_day"] == 45_000
    assert plan["fixed_wallet_admission_count"] is None
    assert plan["fixed_per_run_compute_unit_threshold"] is None
    wallet_endpoints = [
        row
        for row in plan["endpoints"]
        if row["target_count"] == 239
    ]
    assert len(wallet_endpoints) == 6
    assert all(
        row["declared_wallet_tier_counts"]
        == {"T0": 18, "T1": 221, "T2": 0}
        for row in wallet_endpoints
    )
    assert all(
        row["effective_cadence_seconds_tier0"]
        == row["cadence_seconds_tier0"]
        for row in wallet_endpoints
    )


def test_scheduler_plan_month_authority_can_bind_adaptive_run_allowance() -> None:
    budget_status = FixedWindowLimiter(
        remaining_today_cu=26_130,
        remaining_month_cu=30_380,
    ).as_dict()

    plan = provider_loop.moralis_scheduler_plan(
        wallets=[],
        tokens=[LINK_TOKEN],
        metadata_tokens=[LINK_TOKEN],
        budget_status=budget_status,
        scheduler_interval_seconds=300,
        now_utc=datetime(2026, 7, 21, 10, 50, tzinfo=UTC),
    )

    assert plan["daily_paced_run_compute_unit_allowance"] == 165
    assert plan["monthly_paced_run_compute_unit_allowance"] == 10
    assert plan["current_run_compute_unit_budget"] == 10


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
    assert partial["current_run_compute_unit_budget"] == 0
    assert partial["daily_admission_opportunity_count"] == 144
    assert partial["daily_paced_run_compute_unit_allowance"] == 0
    assert partial["earned_compute_units_per_window"] == pytest.approx(50 / 144)
    assert partial["current_run_budget_policy"] == (
        "UTC_REMAINING_AUTHORITY_EARNED_CREDIT_CARRY_V2"
    )
    assert partial["current_run_compute_unit_budget_is_hard_spend_cap"] is False
    assert partial["durable_credit_balance_is_dispatch_authority"] is True
    assert partial["remaining_authority_frontload_allowed"] is False
    assert partial["fixed_wallet_admission_count"] is None
    assert partial["fixed_per_run_compute_unit_threshold"] is None
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
    assert status["status"] == "CONCURRENT_SCHEDULER_RUN_ACTIVE"
    assert status["status_scope"] == "SCHEDULER_RUN_CONTROL_STATE"
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
            if key.startswith("v2:provider:moralis:rotation_cursor_v2:"):
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


def test_fresh_workers_share_one_restart_safe_earned_credit_window(
    monkeypatch: Any,
) -> None:
    redis_client = FakeRedis()
    tokens = [LINK_TOKEN, UNMAPPED_TOKEN]
    _seed_token_map(
        redis_client,
        [
            ("LINKUSDT", "ethereum", LINK_TOKEN),
            ("OTHERUSDT", "ethereum", UNMAPPED_TOKEN),
        ],
    )
    _patch_single_token_endpoint(monkeypatch)
    monkeypatch.setattr(
        provider_loop,
        "publish_moralis_result",
        lambda *args, **kwargs: {"actual_payload_present": False},
    )
    limiter = FixedWindowLimiter(remaining_today_cu=50)
    first_client = RecordingClient()
    first_client.limiter = limiter
    second_client = RecordingClient()
    second_client.limiter = limiter
    third_client = RecordingClient()
    third_client.limiter = limiter
    near_reset = datetime(2026, 7, 21, 23, 59, 59, tzinfo=UTC)

    first = provider_loop.run_once(
        redis_client,
        client=first_client,
        chain="eth",
        wallets=[],
        tokens=tokens,
        symbol="BTCUSDT",
        scheduler_state={},
        scheduler_interval_seconds=300,
        now_utc=near_reset,
    )
    second = provider_loop.run_once(
        redis_client,
        client=second_client,
        chain="eth",
        wallets=[],
        tokens=tokens,
        symbol="BTCUSDT",
        scheduler_state={},
        scheduler_interval_seconds=300,
        now_utc=near_reset,
    )

    assert [call["token"] for call in first_client.calls] == [LINK_TOKEN]
    assert second_client.calls == []
    assert first["paced_cu_admission_claim_count"] == 1
    assert second["durable_cadence_claim_count"] == 1
    assert second["paced_cu_admission_denied_count"] == 1
    assert second["scheduler_run_suppressed_reason"] == (
        "PACED_CU_CREDIT_ACCUMULATING_FOR_NEXT_DUE_JOB"
    )
    assert second["skipped_not_due"][0]["target_fingerprint"] == (
        hashlib.sha256(UNMAPPED_TOKEN.encode()).hexdigest()[:16]
    )
    state = redis_client.paced_states[
        provider_loop.PACED_CU_ADMISSION_WINDOW_PREFIX
    ]
    assert state["credit"] == pytest.approx(0.0)

    redis_client.redis_time_seconds += 300
    third = provider_loop.run_once(
        redis_client,
        client=third_client,
        chain="eth",
        wallets=[],
        tokens=tokens,
        symbol="BTCUSDT",
        scheduler_state={},
        scheduler_interval_seconds=300,
        now_utc=near_reset,
    )

    assert [call["token"] for call in third_client.calls] == [UNMAPPED_TOKEN]
    assert third["request_count"] == 1


def test_paced_credit_state_unavailable_fails_closed_before_dispatch(
    monkeypatch: Any,
) -> None:
    class PaceUnavailableRedis(FakeRedis):
        def eval(self, script: str, numkeys: int, *args: Any) -> Any:
            if "MORALIS_FENCED_PACED_CU_CLAIM_V3" in script:
                raise RuntimeError("paced state unavailable")
            return super().eval(script, numkeys, *args)

    redis_client = PaceUnavailableRedis()
    _seed_token_map(redis_client, [("LINKUSDT", "ethereum", LINK_TOKEN)])
    _patch_single_token_endpoint(monkeypatch)
    client = RecordingClient()
    client.limiter = FixedWindowLimiter(remaining_today_cu=50)

    status = provider_loop.run_once(
        redis_client,
        client=client,
        chain="eth",
        wallets=[],
        tokens=[LINK_TOKEN],
        symbol="BTCUSDT",
        now_utc=datetime(2026, 7, 21, 23, 59, 59, tzinfo=UTC),
    )

    assert client.calls == []
    assert status["request_count"] == 0
    assert status["paced_cu_admission_state_available"] is False
    assert status["durable_fair_rotation"] is False
    assert status["schedule_plan"][
        "all_valid_configured_targets_eventually_eligible"
    ] is False
    assert status["scheduler_run_suppressed_reason"] == (
        "PACED_CU_ADMISSION_STATE_UNAVAILABLE"
    )
    assert status["status"] == "PACED_CU_ADMISSION_STATE_UNAVAILABLE"
    assert not any(
        key.startswith("v2:provider:moralis:cadence_claim:")
        for key in redis_client.data
    )


def test_non_dispatched_response_releases_earned_credit_and_cadence(
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
    limiter = FixedWindowLimiter(remaining_today_cu=50)
    denied_client = CycleBudgetClient()
    denied_client.limiter = limiter
    denied_client.begin_cycle(dispatches=0)
    near_reset = datetime(2026, 7, 21, 23, 59, 59, tzinfo=UTC)

    denied = provider_loop.run_once(
        redis_client,
        client=denied_client,
        chain="eth",
        wallets=[],
        tokens=[LINK_TOKEN],
        symbol="BTCUSDT",
        now_utc=near_reset,
    )
    state = redis_client.paced_states[
        provider_loop.PACED_CU_ADMISSION_WINDOW_PREFIX
    ]

    assert denied["request_count"] == 0
    assert denied["paced_cu_admission_release_count"] == 1
    assert denied["paced_cu_reservation_created_count"] == 1
    assert denied["paced_cu_reservation_finalize_count"] == 0
    assert denied["paced_cu_reservation_finalize_failure_count"] == 0
    assert denied["paced_cu_reservation_tokens_exposed"] is False
    assert denied["paced_cu_release_exact_once"] is True
    assert state["credit"] == pytest.approx(50.0)
    assert redis_client.paced_reservations == {}
    assert not any(
        key.startswith("v2:provider:moralis:cadence_claim:")
        for key in redis_client.data
    )

    dispatched_client = RecordingClient()
    dispatched_client.limiter = limiter
    dispatched = provider_loop.run_once(
        redis_client,
        client=dispatched_client,
        chain="eth",
        wallets=[],
        tokens=[LINK_TOKEN],
        symbol="BTCUSDT",
        now_utc=near_reset,
    )

    assert dispatched["request_count"] == 1
    assert dispatched["paced_cu_reservation_created_count"] == 1
    assert dispatched["paced_cu_reservation_finalize_count"] == 1
    assert dispatched["paced_cu_reservation_finalize_failure_count"] == 0
    assert len(dispatched_client.calls) == 1
    assert redis_client.paced_reservations == {}
    assert redis_client.paced_states[
        provider_loop.PACED_CU_ADMISSION_WINDOW_PREFIX
    ]["credit"] == pytest.approx(0.0)


def test_dispatched_finalize_failure_stops_new_admission_and_stays_charged(
    monkeypatch: Any,
) -> None:
    class FinalizeUnavailableRedis(FakeRedis):
        def eval(self, script: str, numkeys: int, *args: Any) -> Any:
            if "MORALIS_FENCED_PACED_CU_FINALIZE_V1" in script:
                return 0
            return super().eval(script, numkeys, *args)

    redis_client = FinalizeUnavailableRedis()
    _seed_token_map(redis_client, [("LINKUSDT", "ethereum", LINK_TOKEN)])
    _patch_single_token_endpoint(monkeypatch)
    monkeypatch.setattr(
        provider_loop,
        "publish_moralis_result",
        lambda *args, **kwargs: {"actual_payload_present": False},
    )
    client = RecordingClient()
    client.limiter = FixedWindowLimiter(remaining_today_cu=50)

    status = provider_loop.run_once(
        redis_client,
        client=client,
        chain="eth",
        wallets=[],
        tokens=[LINK_TOKEN],
        symbol="BTCUSDT",
        now_utc=datetime(2026, 7, 21, 23, 59, 59, tzinfo=UTC),
    )

    assert status["request_count"] == 1
    assert status["paced_cu_reservation_created_count"] == 1
    assert status["paced_cu_reservation_finalize_count"] == 0
    assert status["paced_cu_reservation_finalize_failure_count"] == 1
    assert status["paced_cu_admission_state_available"] is False
    assert status["durable_fair_rotation"] is False
    assert status["scheduler_run_suppressed_reason"] == (
        "PACED_CU_RESERVATION_FINALIZE_FAILED"
    )
    assert status["status"] == "PACED_CU_RESERVATION_FINALIZE_FAILED"
    assert redis_client.paced_states[
        provider_loop.PACED_CU_ADMISSION_WINDOW_PREFIX
    ]["credit"] == pytest.approx(0.0)
    assert len(redis_client.paced_reservations) == 1
    serialized_status = json.dumps(status, sort_keys=True)
    serialized_loop_log = json.dumps(
        provider_loop._loop_log_report(status),
        sort_keys=True,
    )
    published_status = redis_client.data[provider_loop.SCHEDULER_STATUS_KEY]
    assert all(
        reservation["reservation_id"] not in serialized_status
        and reservation["reservation_id"] not in serialized_loop_log
        and reservation["reservation_id"] not in published_status
        and reservation["lease_token"] not in serialized_status
        and reservation["lease_token"] not in serialized_loop_log
        and reservation["lease_token"] not in published_status
        for reservation in redis_client.paced_reservations.values()
    )


def test_250_cu_job_dispatches_after_durable_credit_carry_and_exact_debit(
    monkeypatch: Any,
) -> None:
    networth_spec = replace(
        WALLET_SPEC,
        endpoint_id="wallet_networth",
        group="wallet_networth",
        cu_cost=250,
    )
    monkeypatch.setattr(
        provider_loop,
        "moralis_endpoint_registry",
        lambda: (networth_spec,),
    )
    monkeypatch.setattr(
        provider_loop,
        "publish_moralis_feature_payload",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        provider_loop,
        "publish_moralis_result",
        lambda *args, **kwargs: {"actual_payload_present": False},
    )
    redis_client = FakeRedis()
    limiter = FixedWindowLimiter(
        remaining_today_cu=26_130,
        remaining_month_cu=1_945_510,
    )
    first_client = DebitTrackingClient(limiter)
    second_client = DebitTrackingClient(limiter)
    observed_at = datetime(2026, 7, 21, 10, 50, tzinfo=UTC)

    first = provider_loop.run_once(
        redis_client,
        client=first_client,
        chain="eth",
        wallets=["0x" + ("9" * 40)],
        tokens=[],
        symbol="BTCUSDT",
        scheduler_interval_seconds=300,
        now_utc=observed_at,
    )
    initial_credit = float(
        redis_client.paced_states[
            provider_loop.PACED_CU_ADMISSION_WINDOW_PREFIX
        ]["credit"]
    )

    assert first_client.calls == []
    assert first["request_count"] == 0
    assert initial_credit == pytest.approx(26_130 / 158)
    assert limiter.debited_cu == 0

    redis_client.redis_time_seconds += 300
    second = provider_loop.run_once(
        redis_client,
        client=second_client,
        chain="eth",
        wallets=["0x" + ("9" * 40)],
        tokens=[],
        symbol="BTCUSDT",
        scheduler_interval_seconds=300,
        now_utc=observed_at,
    )
    remaining_credit = float(
        redis_client.paced_states[
            provider_loop.PACED_CU_ADMISSION_WINDOW_PREFIX
        ]["credit"]
    )

    assert len(second_client.calls) == 1
    assert second["request_count"] == 1
    assert second["current_run_admitted_compute_units"] == 250
    assert limiter.debited_cu == 250
    assert limiter.remaining_today_cu == 26_130 - 250
    assert remaining_credit == pytest.approx((2 * (26_130 / 158)) - 250)


@pytest.mark.parametrize("crossing", ["day", "month"])
def test_stale_reset_snapshot_cannot_remint_credit_across_utc_boundary(
    crossing: str,
) -> None:
    redis_client = FakeRedis()
    interval = 300
    redis_client.redis_time_seconds = 2_000_000_000
    lease_key = provider_loop._scheduler_lease_key("eth")
    lease_value = hashlib.sha256(b"reset-boundary-lease").hexdigest()
    redis_client.data[lease_key] = lease_value
    day_reset = redis_client.redis_time_seconds + (
        1 if crossing == "day" else 86_400
    )
    month_reset = redis_client.redis_time_seconds + (
        1 if crossing == "month" else 2_592_000
    )

    admitted, available, credit, _window, reservation_id = (
        provider_loop._claim_paced_compute_units(
            redis_client,
            chain="eth",
            lease_token=lease_value,
            scheduler_interval_seconds=interval,
            cost_cu=250,
            remaining_today_cu=165,
            remaining_month_cu=165,
            daily_admission_opportunities=1,
            monthly_admission_opportunities=1,
            utc_day_reset_epoch_seconds=day_reset,
            utc_month_reset_epoch_seconds=month_reset,
        )
    )
    state_before = dict(
        redis_client.paced_states[
            provider_loop.PACED_CU_ADMISSION_WINDOW_PREFIX
        ]
    )
    redis_client.redis_time_seconds += 1

    stale_admitted, stale_available, stale_credit, _stale_window, _stale_reservation = (
        provider_loop._claim_paced_compute_units(
            redis_client,
            chain="eth",
            lease_token=lease_value,
            scheduler_interval_seconds=interval,
            cost_cu=10,
            remaining_today_cu=165,
            remaining_month_cu=165,
            daily_admission_opportunities=1,
            monthly_admission_opportunities=1,
            utc_day_reset_epoch_seconds=day_reset,
            utc_month_reset_epoch_seconds=month_reset,
        )
    )

    assert admitted is False
    assert available is True
    assert credit == pytest.approx(165.0)
    assert reservation_id is None
    assert stale_admitted is False
    assert stale_available is False
    assert stale_credit == 0.0
    assert redis_client.paced_states[
        provider_loop.PACED_CU_ADMISSION_WINDOW_PREFIX
    ] == state_before
def test_elapsed_credit_uses_prior_window_rate_without_retroactive_repricing() -> None:
    redis_client = FakeRedis()
    interval = 300
    redis_client.redis_time_seconds = 2_000_000_000
    lease_value = hashlib.sha256(b"elapsed-credit-lease").hexdigest()
    redis_client.data[provider_loop._scheduler_lease_key("eth")] = lease_value
    day_reset = redis_client.redis_time_seconds + 86_400
    month_reset = redis_client.redis_time_seconds + 2_592_000

    first = provider_loop._claim_paced_compute_units(
        redis_client,
        chain="eth",
        lease_token=lease_value,
        scheduler_interval_seconds=interval,
        cost_cu=10_000,
        remaining_today_cu=1_000,
        remaining_month_cu=10_000,
        daily_admission_opportunities=10,
        monthly_admission_opportunities=100,
        utc_day_reset_epoch_seconds=day_reset,
        utc_month_reset_epoch_seconds=month_reset,
    )
    redis_client.redis_time_seconds += 5 * interval
    second = provider_loop._claim_paced_compute_units(
        redis_client,
        chain="eth",
        lease_token=lease_value,
        scheduler_interval_seconds=interval,
        cost_cu=10_000,
        remaining_today_cu=1_000,
        remaining_month_cu=10_000,
        daily_admission_opportunities=5,
        monthly_admission_opportunities=50,
        utc_day_reset_epoch_seconds=day_reset,
        utc_month_reset_epoch_seconds=month_reset,
    )

    assert first[:3] == (False, True, 100.0)
    assert second[:3] == (False, True, 600.0)
    assert float(
        redis_client.paced_states[
            provider_loop.PACED_CU_ADMISSION_WINDOW_PREFIX
        ]["credit"]
    ) == pytest.approx(600.0)


def test_long_lived_239_candidate_cursor_wrap_revisits_base_cadence_without_restart(
    monkeypatch: Any,
) -> None:
    rows = load_wallet_watchlist_seed(
        observed_at=datetime(2026, 7, 21, 12, 0, tzinfo=UTC)
    )
    candidate_rows = [
        {
            "chain": row["chain"],
            "address": row["address"],
            "tier": row["tier"],
            "source": row["source"],
        }
        for row in rows
        if row["chain"] == "eth"
    ]
    assert len(candidate_rows) == 239
    monkeypatch.setattr(
        provider_loop,
        "read_wallet_watchlist",
        lambda _redis_client: candidate_rows,
    )
    _patch_single_wallet_endpoint(monkeypatch)
    redis_client = ExpiringFakeRedis()
    limiter = FixedWindowLimiter(remaining_today_cu=50)
    client = RecordingClient()
    client.limiter = limiter
    scheduler_state: dict[str, float] = {}
    near_reset = datetime(2026, 7, 21, 23, 59, 59, tzinfo=UTC)
    first_239_statuses: list[dict[str, Any]] = []

    for cycle in range(239):
        redis_client.redis_time_seconds = 1_750_000_000 + (cycle * 300)
        first_239_statuses.append(
            provider_loop.run_once(
                redis_client,
                client=client,
                chain="eth",
                wallets=[],
                tokens=[],
                symbol="BTCUSDT",
                scheduler_state=scheduler_state,
                force=False,
                now_monotonic=float(cycle * 300),
                scheduler_interval_seconds=300,
                now_utc=near_reset,
            )
        )

    first_cycle_wallets = [str(call["wallet"]) for call in client.calls]
    assert len(first_cycle_wallets) == 239
    assert len(set(first_cycle_wallets)) == 239
    assert all(status["request_count"] == 1 for status in first_239_statuses)
    assert all(
        status["adaptive_overload_ratio_applied_to_in_memory_cadence"] is False
        for status in first_239_statuses
    )

    redis_client.redis_time_seconds += 300
    wrap_status = provider_loop.run_once(
        redis_client,
        client=client,
        chain="eth",
        wallets=[],
        tokens=[],
        symbol="BTCUSDT",
        scheduler_state=scheduler_state,
        force=False,
        now_monotonic=float(239 * 300),
        scheduler_interval_seconds=300,
        now_utc=near_reset,
    )

    assert wrap_status["request_count"] == 1
    assert len(client.calls) == 240
    assert client.calls[-1]["wallet"] == first_cycle_wallets[0]
    assert wrap_status["durable_cadence_claim_ttl_max_seconds"] == 600
    assert wrap_status["schedule_plan"]["adaptive_overload_ratio"] > 1.0
    assert wrap_status["schedule_plan"][
        "adaptive_overload_ratio_applied_to_target_cadence"
    ] is False
