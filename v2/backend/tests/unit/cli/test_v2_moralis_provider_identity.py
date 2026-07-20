from __future__ import annotations

import json
from typing import Any

from v2.backend.app.cli import v2_moralis_provider_loop as provider_loop
from v2.backend.app.services.smart_money_wallets.endpoint_registry import (
    MoralisEndpointSpec,
)
from v2.backend.app.services.smart_money_wallets.models import MoralisResponse

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

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        del ex
        self.data[key] = value
        return True


class FakeLimiter:
    def as_dict(self) -> dict[str, Any]:
        return {"compute_budget": {"used_today": 0, "used_month": 0}}


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
            ("BTCUSDT", "ethereum", "0xbtc"),
            ("LINKUSDT", "ethereum", "0xlink"),
        ],
    )

    bootstrap = provider_loop._resolve_bootstrap_inputs(
        redis_client,
        chain="eth",
        symbol="BTCUSDT",
        wallets=[],
        tokens=["0xLINK"],
    )

    assert bootstrap["tokens"] == ["0xLINK"]
    assert bootstrap["contract_symbol_map"][("eth", "0xlink")]["symbol"] == "LINKUSDT"
    assert bootstrap["ambiguous_contract_keys"] == set()


def test_duplicate_contract_identity_is_ambiguous_and_never_requested(monkeypatch: Any) -> None:
    redis_client = FakeRedis()
    _seed_token_map(
        redis_client,
        [
            ("LINKUSDT", "ethereum", "0xshared"),
            ("FAKEUSDT", "eth", "0xshared"),
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
        tokens=["0xshared"],
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
    _seed_token_map(redis_client, [("BTCUSDT", "ethereum", "0xbtc")])
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
        tokens=["0xunmapped"],
        symbol="BTCUSDT",
    )

    assert client.calls == []
    assert published == []
    assert bridge_refreshes[0]["features"] == {}
    assert bridge_refreshes[0]["actual_payload_present"] is False
    assert status["request_count"] == 0
    assert status["identity_rejected_request_count"] == 1
    assert status["quarantined_contracts"][0]["reason"] == "NO_VERIFIED_SYMBOL_MAPPING"


def test_verified_token_is_requested_and_published_under_its_own_symbol(monkeypatch: Any) -> None:
    redis_client = FakeRedis()
    _seed_token_map(
        redis_client,
        [
            ("BTCUSDT", "ethereum", "0xbtc"),
            ("LINKUSDT", "ethereum", "0xlink"),
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
        tokens=["0xLINK"],
        symbol="BTCUSDT",
    )

    assert [call["symbol"] for call in client.calls] == ["LINKUSDT"]
    assert [row["symbol"] for row in published] == ["LINKUSDT"]
    assert status["resolved_symbols"] == ["LINKUSDT"]
    assert status["quarantined_contract_count"] == 0
