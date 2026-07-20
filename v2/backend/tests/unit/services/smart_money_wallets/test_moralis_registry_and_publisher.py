from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from unittest.mock import Mock

import httpx
import pytest

from v2.backend.app.cli import v2_moralis_token_metadata_validate as metadata_validator
from v2.backend.app.services.feature_pipeline.unified_feature_bridge import (
    build_unified_feature_payload,
)
from v2.backend.app.services.smart_money_wallets import moralis_feature_bridge
from v2.backend.app.services.smart_money_wallets import publisher as moralis_publisher
from v2.backend.app.services.smart_money_wallets.address_classifier import classify_address
from v2.backend.app.services.smart_money_wallets.canonical_cache import (
    read_canonical_records,
)
from v2.backend.app.services.smart_money_wallets.client import (
    MoralisClient,
    _request_contract_error,
)
from v2.backend.app.services.smart_money_wallets.endpoint_registry import (
    MORALIS_CU_PRICING_VERIFIED_ON,
    MORALIS_DATA_API_CU_PRICING_SOURCE,
    MORALIS_DEEP_INDEX_BASE_URL,
    MORALIS_STREAMS_CU_PRICING_SOURCE,
    moralis_endpoint_registry,
    registry_payload,
)
from v2.backend.app.services.smart_money_wallets.health import build_moralis_health
from v2.backend.app.services.smart_money_wallets.moralis_feature_bridge import (
    FEATURE_NAMES,
    build_moralis_feature_payload,
    publish_moralis_feature_payload,
)
from v2.backend.app.services.smart_money_wallets.normalizer import (
    normalize_moralis_payload,
)
from v2.backend.app.services.smart_money_wallets.publisher import publish_moralis_result
from v2.backend.app.services.smart_money_wallets.smart_wallet_scorer import score_wallet_candidate
from v2.backend.app.services.smart_money_wallets.streams_registry import build_streams_registry
from v2.backend.app.services.smart_money_wallets.token_contract_mapper import (
    load_token_contract_map,
    read_metadata_validation_tokens,
    read_pollable_tokens,
)
from v2.backend.app.services.smart_money_wallets.wallet_watchlist import (
    TIER_LIMITS,
    load_wallet_watchlist_seed,
    publish_wallet_watchlist,
    read_wallet_watchlist,
    wallet_watchlist_status,
)

VALID_TOKEN_ADDRESS = "0x" + ("1" * 40)
VALID_WALLET_ADDRESS = "0x" + ("2" * 40)


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

    def ttl(self, key: str) -> int:
        if key not in self.data:
            return -2
        return self.ttls.get(key, -1)

    def scan_iter(self, pattern: str, count: int = 500):
        del count
        prefix = pattern.removesuffix("*")
        yield from (key for key in sorted(self.data) if key.startswith(prefix))


def _seed_link_token_map(redis_client: FakeRedis) -> tuple[dict[str, object], str]:
    loaded = load_token_contract_map()
    row = deepcopy(loaded["symbols"]["LINKUSDT"])
    contract = row["contracts"][0]
    token = str(contract["contract_address"])
    redis_client.set("v2:moralis:token_map:LINKUSDT", json.dumps(row), ex=3600)
    redis_client.set(
        "v2:moralis:token_map_status",
        json.dumps(
            {
                "schema_version": "moralis_token_map_status_v1",
                "status": "TOKEN_MAP_READY",
                "symbols": ["LINKUSDT"],
                "token_map_count": 1,
            }
        ),
        ex=3600,
    )
    return row, token


def test_registry_exposes_wallet_token_stream_cadence_and_cu() -> None:
    payload = registry_payload()
    endpoints = {row["endpoint_id"]: row for row in payload["endpoints"]}
    assert payload["daily_compute_unit_budget"] == 55_000
    assert endpoints["wallet_token_balances_price"]["requires_wallet"] is True
    assert endpoints["wallet_networth"]["requires_wallet"] is True
    assert endpoints["token_transfers"]["requires_token"] is True
    assert endpoints["token_metadata"]["requires_token"] is True
    assert endpoints["streams"]["stream_based"] is True
    assert endpoints["streams"]["cadence_seconds_tier0"] == 0


def test_registry_cu_reservations_cover_verified_official_costs() -> None:
    payload = registry_payload()
    endpoints = {row["endpoint_id"]: row for row in payload["endpoints"]}
    official_cost_floor = {
        "wallet_token_balances_price": 100,
        "wallet_history": 150,
        "wallet_transactions": 30,
        "wallet_networth": 250,
        "wallet_address_transfers": 50,
        "token_transfers": 50,
        "token_address_transfers": 50,
        "token_holders": 50,
        "wallet_swaps": 50,
        "token_swaps": 50,
        "token_metadata": 10,
        "token_price": 50,
        "multiple_token_prices": 100,
        "streams": 10,
    }

    assert set(endpoints) == set(official_cost_floor)
    assert all(
        endpoints[endpoint_id]["cu_cost"] >= official_cost
        for endpoint_id, official_cost in official_cost_floor.items()
    )
    assert endpoints["wallet_networth"]["cu_cost"] == 250
    assert endpoints["multiple_token_prices"]["cu_cost"] == 100
    assert payload["compute_unit_pricing"] == {
        "data_api_source": MORALIS_DATA_API_CU_PRICING_SOURCE,
        "streams_source": MORALIS_STREAMS_CU_PRICING_SOURCE,
        "verified_on": MORALIS_CU_PRICING_VERIFIED_ON,
        "estimate_policy": "OFFICIAL_CURRENT_OR_CONSERVATIVE_WHEN_IDENTITY_UNVERIFIED",
    }


def test_registry_matches_current_official_request_contracts_endpoint_by_endpoint() -> None:
    endpoint_contracts = {
        "wallet_token_balances_price": (
            "GET",
            MORALIS_DEEP_INDEX_BASE_URL,
            "/wallets/{wallet}/tokens?chain={chain}",
            ("chain={chain}",),
            None,
            100,
            "PER_REQUEST",
            True,
            None,
            "https://docs.moralis.com/data-api/evm/wallet/token-balances",
        ),
        "wallet_history": (
            "GET",
            MORALIS_DEEP_INDEX_BASE_URL,
            "/wallets/{wallet}/history?chain={chain}",
            ("chain={chain}",),
            None,
            150,
            "PER_REQUEST",
            True,
            None,
            "https://docs.moralis.com/data-api/evm/wallet/wallet-history",
        ),
        "wallet_transactions": (
            "GET",
            MORALIS_DEEP_INDEX_BASE_URL,
            "/{wallet}?chain={chain}",
            ("chain={chain}",),
            None,
            30,
            "PER_REQUEST",
            True,
            None,
            "https://docs.moralis.com/data-api/evm/wallet/wallet-transactions",
        ),
        "wallet_networth": (
            "GET",
            MORALIS_DEEP_INDEX_BASE_URL,
            "/wallets/{wallet}/net-worth?chains={chain}",
            ("chains={chain}",),
            None,
            250,
            "PER_CHAIN",
            True,
            None,
            "https://docs.moralis.com/data-api/evm/wallet/net-worth",
        ),
        "wallet_address_transfers": (
            "GET",
            MORALIS_DEEP_INDEX_BASE_URL,
            "/{wallet}/erc20/transfers?chain={chain}",
            ("chain={chain}",),
            None,
            50,
            "PER_REQUEST",
            True,
            None,
            "https://docs.moralis.com/data-api/evm/wallet/token-transfers",
        ),
        "token_transfers": (
            "GET",
            MORALIS_DEEP_INDEX_BASE_URL,
            "/erc20/{token}/transfers?chain={chain}",
            ("chain={chain}",),
            None,
            50,
            "PER_REQUEST",
            True,
            None,
            "https://docs.moralis.com/data-api/evm/token/transfers/token-transfers",
        ),
        "token_address_transfers": (
            "GET",
            MORALIS_DEEP_INDEX_BASE_URL,
            "/erc20/{token}/transfers?chain={chain}",
            ("chain={chain}",),
            None,
            50,
            "PER_REQUEST",
            False,
            "DUPLICATE_TRANSPORT_ALIAS_NOT_DIRECTLY_POLLED",
            "https://docs.moralis.com/data-api/evm/token/transfers/token-transfers",
        ),
        "token_holders": (
            "GET",
            MORALIS_DEEP_INDEX_BASE_URL,
            "/erc20/{token}/owners?chain={chain}",
            ("chain={chain}",),
            None,
            50,
            "PER_REQUEST",
            True,
            None,
            "https://docs.moralis.com/data-api/evm/token/holders/token-holders",
        ),
        "wallet_swaps": (
            "GET",
            MORALIS_DEEP_INDEX_BASE_URL,
            "/wallets/{wallet}/swaps?chain={chain}",
            ("chain={chain}",),
            None,
            50,
            "PER_REQUEST",
            True,
            None,
            "https://docs.moralis.com/data-api/evm/wallet/wallet-swaps",
        ),
        "token_swaps": (
            "GET",
            MORALIS_DEEP_INDEX_BASE_URL,
            "/erc20/{token}/swaps?chain={chain}",
            ("chain={chain}",),
            None,
            50,
            "PER_REQUEST",
            True,
            None,
            "https://docs.moralis.com/data-api/evm/token/swaps/token-swaps",
        ),
        "token_metadata": (
            "GET",
            MORALIS_DEEP_INDEX_BASE_URL,
            "/erc20/metadata?chain={chain}&addresses={token}",
            ("chain={chain}", "addresses={token}"),
            None,
            10,
            "PER_REQUEST",
            True,
            None,
            "https://docs.moralis.com/data-api/evm/token/metadata/token-metadata",
        ),
        "token_price": (
            "GET",
            MORALIS_DEEP_INDEX_BASE_URL,
            "/erc20/{token}/price?chain={chain}",
            ("chain={chain}",),
            None,
            50,
            "PER_REQUEST",
            True,
            None,
            "https://docs.moralis.com/data-api/evm/token/prices/token-price",
        ),
        "multiple_token_prices": (
            "POST",
            MORALIS_DEEP_INDEX_BASE_URL,
            "/erc20/prices?chain={chain}",
            ("chain={chain}",),
            '{"tokens":[{"token_address":"{token}"}]}',
            100,
            "PER_REQUEST",
            False,
            "ENDPOINT_POST_BATCH_BODY_AND_SCHEDULING_UNSUPPORTED",
            "https://docs.moralis.com/data-api/evm/token/prices/token-prices-batch",
        ),
        "streams": (
            "WEBHOOK",
            None,
            "webhook",
            (),
            "PROVIDER_STREAM_EVENT",
            10,
            "PER_CONFIRMED_RECORD",
            False,
            "STREAM_ENDPOINT_NOT_POLLED",
            MORALIS_STREAMS_CU_PRICING_SOURCE,
        ),
    }
    specs = {spec.endpoint_id: spec for spec in moralis_endpoint_registry()}

    assert set(specs) == set(endpoint_contracts)
    for endpoint_id, expected_contract in endpoint_contracts.items():
        spec = specs[endpoint_id]
        actual_contract = (
            spec.http_method,
            spec.documented_base_url,
            spec.path_template,
            spec.query_parameter_shape,
            spec.request_body_shape,
            spec.cu_cost,
            spec.cu_cost_unit,
            spec.polling_supported,
            spec.polling_block_reason,
            spec.contract_reference,
        )
        assert actual_contract == expected_contract, endpoint_id


def test_all_admitted_polling_specs_pass_the_client_request_contract_guard() -> None:
    admitted = [
        spec
        for spec in moralis_endpoint_registry()
        if spec.polling_supported and not spec.stream_based
    ]
    assert admitted
    assert all(_request_contract_error(spec) is None for spec in admitted)
    alias = next(
        spec
        for spec in moralis_endpoint_registry()
        if spec.endpoint_id == "token_address_transfers"
    )
    assert alias.transport_alias_of == "token_transfers"
    assert _request_contract_error(alias) == "ENDPOINT_TRANSPORT_ALIAS_NOT_DIRECTLY_POLLED"


def test_unsupported_batch_contract_fails_before_cu_reservation_or_http() -> None:
    spec = next(
        spec for spec in moralis_endpoint_registry() if spec.endpoint_id == "multiple_token_prices"
    )
    limiter = Mock()
    http_client = Mock()
    response = MoralisClient(
        api_key="secret",
        limiter=limiter,
        http_client=http_client,  # type: ignore[arg-type]
    ).get(
        spec,
        chain="eth",
        token=VALID_TOKEN_ADDRESS,
        symbol="LINKUSDT",
    )

    assert response.error_class == "ENDPOINT_POST_BATCH_BODY_AND_SCHEDULING_UNSUPPORTED"
    assert response.http_status is None
    assert response.payload is None
    limiter.allow_request.assert_not_called()
    http_client.get.assert_not_called()


@pytest.mark.parametrize(
    ("spec", "expected_error"),
    [
        (
            replace(
                next(
                    spec
                    for spec in moralis_endpoint_registry()
                    if spec.endpoint_id == "multiple_token_prices"
                ),
                polling_supported=True,
            ),
            "ENDPOINT_HTTP_METHOD_UNSUPPORTED",
        ),
        (
            replace(
                next(
                    spec
                    for spec in moralis_endpoint_registry()
                    if spec.endpoint_id == "token_price"
                ),
                documented_base_url="https://api.moralis.example/v1",
            ),
            "ENDPOINT_BASE_URL_UNSUPPORTED",
        ),
        (
            replace(
                next(
                    spec
                    for spec in moralis_endpoint_registry()
                    if spec.endpoint_id == "token_price"
                ),
                path_template="/erc20/{token}/price?chains={chain}",
            ),
            "ENDPOINT_QUERY_CONTRACT_MISMATCH",
        ),
    ],
)
def test_mismatched_request_contract_fails_before_cu_reservation_or_http(
    spec, expected_error: str
) -> None:
    limiter = Mock()
    http_client = Mock()
    response = MoralisClient(
        api_key="secret",
        limiter=limiter,
        http_client=http_client,  # type: ignore[arg-type]
    ).get(
        spec,
        chain="eth",
        token=VALID_TOKEN_ADDRESS,
        symbol="LINKUSDT",
    )

    assert response.error_class == expected_error
    assert response.http_status is None
    assert response.payload is None
    assert response.request_dispatched is False
    limiter.allow_request.assert_not_called()
    http_client.get.assert_not_called()


def test_client_base_url_mismatch_fails_before_cu_reservation_or_http() -> None:
    spec = next(spec for spec in moralis_endpoint_registry() if spec.endpoint_id == "token_price")
    limiter = Mock()
    http_client = Mock()
    response = MoralisClient(
        api_key="secret",  # noqa: S106 - non-secret test fixture
        base_url="https://untrusted.example",
        limiter=limiter,  # type: ignore[arg-type]
        http_client=http_client,
    ).get(
        spec,
        chain="eth",
        token=VALID_TOKEN_ADDRESS,
        symbol="LINKUSDT",
    )

    assert response.error_class == "ENDPOINT_CLIENT_BASE_URL_MISMATCH"
    assert response.http_status is None
    limiter.allow_request.assert_not_called()
    http_client.get.assert_not_called()


@pytest.mark.parametrize(
    ("endpoint_id", "chain", "wallet", "token", "expected_error"),
    [
        ("wallet_history", "eth", None, None, "WALLET_REQUIRED"),
        ("token_price", "eth", None, None, "TOKEN_REQUIRED"),
        ("token_price", "", None, VALID_TOKEN_ADDRESS, "CHAIN_REQUIRED"),
        (
            "token_price",
            "eth?chain=polygon",
            None,
            VALID_TOKEN_ADDRESS,
            "CHAIN_UNSUPPORTED",
        ),
        ("token_price", "eth", None, f"{VALID_TOKEN_ADDRESS}&limit=1", "TOKEN_ADDRESS_INVALID"),
        (
            "wallet_history",
            "eth",
            f"{VALID_WALLET_ADDRESS}/history",
            None,
            "WALLET_ADDRESS_INVALID",
        ),
    ],
)
def test_required_request_identity_fails_before_cu_reservation_or_http(
    endpoint_id: str,
    chain: str,
    wallet: str | None,
    token: str | None,
    expected_error: str,
) -> None:
    spec = next(spec for spec in moralis_endpoint_registry() if spec.endpoint_id == endpoint_id)
    limiter = Mock()
    http_client = Mock()
    response = MoralisClient(
        api_key="secret",
        limiter=limiter,
        http_client=http_client,  # type: ignore[arg-type]
    ).get(spec, chain=chain, wallet=wallet, token=token)

    assert response.error_class == expected_error
    assert response.http_status is None
    assert response.payload is None
    assert response.request_dispatched is False
    limiter.allow_request.assert_not_called()
    http_client.get.assert_not_called()


def test_client_normalizes_identity_and_builds_query_without_string_injection() -> None:
    spec = next(spec for spec in moralis_endpoint_registry() if spec.endpoint_id == "token_price")
    limiter = Mock()
    limiter.allow_request.return_value = Mock(allowed=True, reservation=None)
    limiter.reconcile_response.return_value = Mock(applied=True)
    http_client = Mock()
    http_client.get.return_value = httpx.Response(200, json={"usdPrice": 1.0})
    mixed_case_token = "0x" + ("Ab" * 20)

    response = MoralisClient(
        api_key="secret",  # noqa: S106 - non-secret test fixture
        limiter=limiter,  # type: ignore[arg-type]
        http_client=http_client,
    ).get(spec, chain=" Ethereum ", token=mixed_case_token)

    assert response.request_dispatched is True
    assert response.chain == "eth"
    assert response.token == mixed_case_token.lower()
    requested_url = http_client.get.call_args.args[0]
    assert requested_url == (
        f"{MORALIS_DEEP_INDEX_BASE_URL}/erc20/{mixed_case_token.lower()}/price?chain=eth"
    )


def test_stream_endpoint_is_not_polled_by_client() -> None:
    spec = next(s for s in moralis_endpoint_registry() if s.endpoint_id == "streams")
    response = MoralisClient(api_key="secret").get(spec, chain="eth", symbol="BTCUSDT")
    assert response.error_class == "STREAM_ENDPOINT_NOT_POLLED"
    assert response.http_status is None


def test_publisher_writes_wallet_token_signal_feature_and_endpoint_status() -> None:
    r = FakeRedis()
    spec = next(s for s in moralis_endpoint_registry() if s.endpoint_id == "token_transfers")
    result = publish_moralis_result(
        r,
        env={"MORALIS_API_KEY": "secret"},
        spec=spec,
        chain="eth",
        symbol="BTCUSDT",
        token="0xtoken",  # noqa: S106 - fixture token identifier, not a credential
        http_status=200,
        payload={
            "result": [
                {"direction": "out", "value_usd": 1200, "block_timestamp": "2026-07-08T12:00:00Z"}
            ]
        },
        budget_status={"compute_budget": {"used_today": 50, "used_month": 50}},
        token_map_count=1,
        wallet_watchlist_count=1,
    )
    assert result["actual_payload_present"] is True
    assert "v2:moralis:token_transfers:eth:0xtoken" in r.data
    assert "v2:features:moralis:BTCUSDT:1m" in r.data
    assert "v2:smart_money:signals:BTCUSDT" in r.data
    endpoint_status = json.loads(r.data["v2:provider:moralis:endpoint_status"])
    assert endpoint_status["endpoints"]["token_transfers"]["actual_payload_present"] is True
    feature_payload = json.loads(r.data["v2:features:moralis:BTCUSDT:1m"])
    assert feature_payload["schema_version"] == "moralis_feature_bridge_v1"
    assert feature_payload["source_actual_payload_present"] is True
    assert feature_payload["source_feature_count"] == 3
    assert feature_payload["actual_payload_present"] is False
    assert feature_payload["features"] == {}
    assert feature_payload["trainer_admission_status"] == "ISOLATED_BY_POLICY"
    assert feature_payload["decision_time_safe"] is False
    assert feature_payload["feature_bridge_ready"] is False
    assert feature_payload["missing_feature_flags"]
    health = json.loads(r.data["v2:provider:moralis:health"])
    assert health["dashboard_color"] == "GRAY"
    assert health["source_health_status"] == "PARTIAL_REQUIRED_FEATURES_MISSING"
    assert health["source_actual_payload_present"] is True
    assert health["trainer_consumption_status"] == "ISOLATED_BY_POLICY"
    assert health["feature_bridge_ready"] is False
    assert health["missing_mask_true"] is True
    assert health["token_map_count"] == 1
    assert health["wallet_watchlist_count"] == 1


def test_publisher_merges_moralis_endpoint_features() -> None:
    r = FakeRedis()
    transfers = next(s for s in moralis_endpoint_registry() if s.endpoint_id == "token_transfers")
    swaps = next(s for s in moralis_endpoint_registry() if s.endpoint_id == "wallet_swaps")

    publish_moralis_result(
        r,
        env={"MORALIS_API_KEY": "secret"},
        spec=transfers,
        chain="eth",
        symbol="BTCUSDT",
        token="0xtoken",  # noqa: S106 - fixture token identifier, not a credential
        http_status=200,
        payload={
            "result": [
                {"direction": "out", "value_usd": 1200, "block_timestamp": "2026-07-08T12:00:00Z"}
            ]
        },
        budget_status={"compute_budget": {"used_today": 50, "used_month": 50}},
        token_map_count=1,
        wallet_watchlist_count=1,
    )
    publish_moralis_result(
        r,
        env={"MORALIS_API_KEY": "secret"},
        spec=swaps,
        chain="eth",
        symbol="BTCUSDT",
        wallet="0xwallet",
        http_status=200,
        payload={
            "result": [
                {"side": "buy", "total_value_usd": 800, "block_timestamp": "2026-07-08T12:01:00Z"}
            ]
        },
        budget_status={"compute_budget": {"used_today": 100, "used_month": 100}},
        token_map_count=1,
        wallet_watchlist_count=1,
    )

    aggregate_payload = json.loads(r.data["v2:moralis:feature_aggregate:BTCUSDT:1m"])
    assert set(aggregate_payload["endpoint_payloads"]) == {"token_transfers", "wallet_swaps"}
    assert aggregate_payload["actual_payload_endpoint_count"] == 2

    feature_payload = json.loads(r.data["v2:features:moralis:BTCUSDT:1m"])
    assert feature_payload["schema_version"] == "moralis_feature_bridge_v1"
    assert feature_payload["source_actual_payload_present"] is True
    assert feature_payload["source_feature_count"] == 9
    assert feature_payload["actual_payload_present"] is False
    assert feature_payload["features"] == {}
    assert (
        aggregate_payload["endpoint_payloads"]["token_transfers"]["features"][
            "moralis_net_exchange_flow_usd"
        ]
        == 1200
    )
    assert (
        aggregate_payload["endpoint_payloads"]["wallet_swaps"]["features"][
            "moralis_dex_buy_pressure_usd"
        ]
        == 800
    )
    assert "endpoint_payloads" not in feature_payload
    assert feature_payload["feature_bridge_ready"] is False
    assert "moralis_holder_count" in feature_payload["missing_feature_flags"]


def test_publisher_does_not_launder_invalid_prior_endpoint_clocks() -> None:
    redis_client = FakeRedis()
    redis_client.set(
        "v2:moralis:feature_aggregate:BTCUSDT:1m",
        json.dumps(
            {
                "endpoint_payloads": {
                    "wallet_swaps": {
                        "endpoint_id": "wallet_swaps",
                        "features": {"moralis_dex_buy_pressure_usd": 999.0},
                        "event_time": "2026-07-08T12:00:00",
                        "feature_cutoff": "2026-07-08T12:00:00Z",
                        "generated_at": "2026-07-08T12:00:01Z",
                        "available_at": "2026-07-08T12:00:02Z",
                        "expires_at": "2099-07-08T12:00:02Z",
                        "actual_payload_present": True,
                    }
                }
            }
        ),
        ex=3600,
    )
    transfers = next(
        spec for spec in moralis_endpoint_registry() if spec.endpoint_id == "token_transfers"
    )

    publish_moralis_result(
        redis_client,
        env={"MORALIS_API_KEY": "secret"},
        spec=transfers,
        chain="eth",
        symbol="BTCUSDT",
        token="0xtoken",  # noqa: S106 - fixture token identifier, not a credential
        http_status=200,
        payload={
            "result": [
                {
                    "direction": "out",
                    "value_usd": 1200,
                    "block_timestamp": "2026-07-08T12:01:00Z",
                }
            ]
        },
        budget_status={"compute_budget": {"used_today": 50, "used_month": 50}},
        token_map_count=1,
        wallet_watchlist_count=1,
    )

    aggregate = json.loads(redis_client.data["v2:moralis:feature_aggregate:BTCUSDT:1m"])
    assert set(aggregate["endpoint_payloads"]) == {"token_transfers"}
    assert "moralis_dex_buy_pressure_usd" not in aggregate["features"]
    assert (
        "wallet_swaps:EVENT_TIME_NOT_STRICT_UTC" in aggregate["endpoint_temporal_rejection_reasons"]
    )


def test_publisher_blocks_later_future_row_hidden_behind_an_earlier_first_row() -> None:
    redis_client = FakeRedis()
    transfers = next(
        spec for spec in moralis_endpoint_registry() if spec.endpoint_id == "token_transfers"
    )

    publish_moralis_result(
        redis_client,
        env={"MORALIS_API_KEY": "secret"},
        spec=transfers,
        chain="eth",
        symbol="BTCUSDT",
        token="0xtoken",  # noqa: S106 - fixture token identifier, not a credential
        http_status=200,
        payload={
            "result": [
                {
                    "direction": "out",
                    "value_usd": 800,
                    "block_timestamp": "2026-07-08T12:00:00Z",
                },
                {
                    "direction": "out",
                    "value_usd": 1200,
                    "block_timestamp": "2099-07-08T12:00:00Z",
                },
            ]
        },
        budget_status={"compute_budget": {"used_today": 50, "used_month": 50}},
        token_map_count=1,
        wallet_watchlist_count=1,
    )

    canonical = json.loads(redis_client.data["v2:features:moralis:BTCUSDT:1m"])
    aggregate = json.loads(redis_client.data["v2:moralis:feature_aggregate:BTCUSDT:1m"])
    bridge_status = json.loads(redis_client.data["v2:provider:moralis:feature_bridge_status"])
    assert canonical["actual_payload_present"] is False
    assert canonical["heartbeat_only"] is True
    assert canonical["features"] == {}
    assert canonical["source_temporal_contract_valid"] is False
    assert canonical["event_time"] is None
    assert canonical["feature_cutoff"] is None
    assert any(
        reason.endswith("EVENT_TIME_AFTER_OBSERVED_AT")
        for reason in canonical["source_temporal_rejection_reasons"]
    )
    assert bridge_status["source_temporal_contract_valid"] is False
    assert bridge_status["source_status"] == "TEMPORAL_CONTRACT_REJECTED"
    assert aggregate["actual_payload_endpoint_count"] == 0
    assert any(
        reason.endswith("EVENT_TIME_AFTER_OBSERVED_AT")
        for reason in aggregate["endpoint_temporal_rejection_reasons"]
    )
    health = json.loads(redis_client.data["v2:provider:moralis:health"])
    assert health["source_health_status"] != "READY"
    assert health["source_temporal_contract_valid"] is False
    assert any(
        reason.endswith("EVENT_TIME_AFTER_OBSERVED_AT")
        for reason in health["source_temporal_rejection_reasons"]
    )
    assert health["trusted_source_actual_endpoint_count"] == 0
    assert health["raw_transport_actual_endpoint_count"] == 1


def test_publisher_uses_latest_clock_across_out_of_order_contributing_rows() -> None:
    redis_client = FakeRedis()
    transfers = next(
        spec for spec in moralis_endpoint_registry() if spec.endpoint_id == "token_transfers"
    )

    publish_moralis_result(
        redis_client,
        env={"MORALIS_API_KEY": "secret"},
        spec=transfers,
        chain="eth",
        symbol="BTCUSDT",
        token="0xtoken",  # noqa: S106 - fixture token identifier, not a credential
        http_status=200,
        payload={
            "result": [
                {
                    "direction": "out",
                    "value_usd": 300,
                    "block_timestamp": "2026-07-08T12:02:00Z",
                },
                {
                    "direction": "out",
                    "value_usd": 1200,
                    "block_timestamp": "2026-07-08T12:00:00Z",
                },
            ]
        },
        budget_status={"compute_budget": {"used_today": 50, "used_month": 50}},
        token_map_count=1,
        wallet_watchlist_count=1,
    )

    aggregate = json.loads(redis_client.data["v2:moralis:feature_aggregate:BTCUSDT:1m"])
    endpoint = aggregate["endpoint_payloads"]["token_transfers"]

    assert endpoint["event_time"] == "2026-07-08T12:02:00Z"
    assert endpoint["feature_cutoff"] == "2026-07-08T12:02:00Z"
    assert endpoint["features"]["moralis_exchange_outflow_usd"] == 1500


def test_publisher_rejects_aggregate_when_any_contributing_row_lacks_a_clock() -> None:
    redis_client = FakeRedis()
    transfers = next(
        spec for spec in moralis_endpoint_registry() if spec.endpoint_id == "token_transfers"
    )

    publish_moralis_result(
        redis_client,
        env={"MORALIS_API_KEY": "secret"},
        spec=transfers,
        chain="eth",
        symbol="BTCUSDT",
        token="0xtoken",  # noqa: S106 - fixture token identifier, not a credential
        http_status=200,
        payload={
            "result": [
                {
                    "direction": "out",
                    "value_usd": 300,
                    "block_timestamp": "2026-07-08T12:02:00Z",
                },
                {"direction": "out", "value_usd": 1200},
            ]
        },
        budget_status={"compute_budget": {"used_today": 50, "used_month": 50}},
        token_map_count=1,
        wallet_watchlist_count=1,
    )

    aggregate = json.loads(redis_client.data["v2:moralis:feature_aggregate:BTCUSDT:1m"])

    assert aggregate["actual_payload_endpoint_count"] == 0
    assert aggregate["endpoint_payloads"] == {}
    assert "token_transfers:EVENT_TIME_MISSING" in aggregate["endpoint_temporal_rejection_reasons"]
    assert (
        "token_transfers:FEATURE_CUTOFF_MISSING" in aggregate["endpoint_temporal_rejection_reasons"]
    )


def test_auth_backoff_status_stays_gray_not_degraded_yellow() -> None:
    r = FakeRedis()
    spec = next(s for s in moralis_endpoint_registry() if s.endpoint_id == "token_holders")

    result = publish_moralis_result(
        r,
        env={"MORALIS_API_KEY": "secret"},
        spec=spec,
        chain="eth",
        symbol="BTCUSDT",
        token="0xtoken",  # noqa: S106 - fixture token identifier, not a credential
        http_status=None,
        payload=None,
        budget_status={"compute_budget": {"used_today": 0, "used_month": 0}},
        error_class="CONFIGURED_BUT_UNSUBSCRIBED_OR_FORBIDDEN",
    )

    assert result["status"] == "CONFIGURED_BUT_UNSUBSCRIBED_OR_FORBIDDEN"
    endpoint_status = json.loads(r.data["v2:provider:moralis:endpoint_status"])
    row = endpoint_status["endpoints"]["token_holders"]
    assert row["actual_payload_present"] is False
    assert row["heartbeat_only"] is True
    assert row["dashboard_color"] == "GRAY"
    health = json.loads(r.data["v2:provider:moralis:health"])
    assert health["dashboard_color"] == "GRAY"


def test_source_health_stays_visible_while_trainer_consumption_remains_isolated() -> None:
    r = FakeRedis()
    transfers = next(s for s in moralis_endpoint_registry() if s.endpoint_id == "token_transfers")
    swaps = next(s for s in moralis_endpoint_registry() if s.endpoint_id == "wallet_swaps")

    publish_moralis_result(
        r,
        env={"MORALIS_API_KEY": "secret"},
        spec=transfers,
        chain="eth",
        symbol="BTCUSDT",
        token="0xtoken",  # noqa: S106 - fixture token identifier, not a credential
        http_status=200,
        payload={
            "result": [
                {"direction": "out", "value_usd": 1200, "block_timestamp": "2026-07-08T12:00:00Z"}
            ]
        },
        budget_status={"compute_budget": {"used_today": 50, "used_month": 50}},
        token_map_count=1,
        wallet_watchlist_count=1,
    )
    publish_moralis_result(
        r,
        env={"MORALIS_API_KEY": "secret"},
        spec=swaps,
        chain="eth",
        symbol="BTCUSDT",
        wallet="0xwallet",
        http_status=None,
        payload=None,
        budget_status={"compute_budget": {"used_today": 50, "used_month": 50}},
        error_class="ConnectTimeout",
        token_map_count=1,
        wallet_watchlist_count=1,
    )

    endpoint_status = json.loads(r.data["v2:provider:moralis:endpoint_status"])
    assert endpoint_status["actual_payload_endpoint_count"] == 1
    health = json.loads(r.data["v2:provider:moralis:health"])
    assert health["status"] == "ISOLATED_BY_POLICY"
    assert health["actual_payload_count_5m"] == 1
    assert health["source_health_status"] == "PARTIAL_REQUIRED_FEATURES_MISSING"
    assert health["source_status"] == "PARTIAL_REQUIRED_FEATURES_MISSING"
    assert health["source_dashboard_color"] == "YELLOW"
    assert health["dashboard_color"] == "GRAY"
    assert health["trainer_decision_time_safe"] is False


def test_configured_key_without_watchlist_is_gray_no_watchlist() -> None:
    health = build_moralis_health({"MORALIS_API_KEY": "secret"})
    assert health["status"] == "CONFIGURED_NO_WATCHLIST"
    assert health["dashboard_color"] == "GRAY"
    assert health["core_system_blocked"] is False


def test_token_contract_map_loads_but_requires_metadata_for_placeholders() -> None:
    payload = load_token_contract_map()
    assert payload["symbol_count"] >= 5
    assert payload["symbols"]["PYTHUSDT"]["tradeable_mapping_status"] == "NEEDS_METADATA_VALIDATION"
    assert payload["symbols"]["PYTHUSDT"]["manual_review_required"] is True
    assert payload["raw_key_exposed"] is False


def test_address_classifier_never_counts_burn_or_contract_as_smart_money() -> None:
    burn = classify_address(chain="eth", address="0x000000000000000000000000000000000000dead")
    assert burn["category"] == "burn_address"
    assert burn["counts_as_smart_money"] is False
    contract = classify_address(chain="eth", address="0xabc", metadata={"is_contract": True})
    assert contract["category"] == "unknown_contract"
    assert contract["smart_wallet_eligible"] is False
    candidate = classify_address(chain="eth", address=VALID_WALLET_ADDRESS)
    assert candidate["smart_wallet_eligible"] is True
    assert candidate["counts_as_smart_money"] is False


def test_wallet_watchlist_seed_bootstraps_candidate_rows_with_tier_limits() -> None:
    rows = load_wallet_watchlist_seed()
    status = wallet_watchlist_status(
        rows, source_path="v2/config/moralis/wallet_watchlist_seed.yaml"
    )

    assert rows
    assert status["status"] == "WATCHLIST_READY"
    assert status["dashboard_color"] == "YELLOW"
    assert status["wallet_watchlist_count"] == len(rows)
    assert status["tier_counts"]["T0"] <= TIER_LIMITS["T0"]
    assert status["tier_counts"]["T1"] <= TIER_LIMITS["T1"]
    assert status["wallets_added_without_source"] is False
    assert status["empty_wallet_list_marked_green"] is False
    assert status["raw_key_exposed"] is False
    assert all(row["bootstrap_status"] == "SEEDED_NOT_VERIFIED" for row in rows)
    assert all(row["source"] for row in rows)
    assert all(row["raw_key_exposed"] is False for row in rows)


def test_smart_wallet_scorer_never_verifies_without_history_or_for_contracts() -> None:
    low_history = score_wallet_candidate(
        chain="eth",
        address="0xwallet",
        features={
            "realized_profit_proxy": 1,
            "win_rate_proxy": 1,
            "entry_timing_score": 1,
            "exit_timing_score": 1,
            "history_event_count": 3,
        },
    )
    assert low_history["label"] != "VERIFIED_SMART_WALLET"
    contract = score_wallet_candidate(
        chain="eth",
        address="0xcontract",
        features={"history_event_count": 100},
        classification={"category": "unknown_contract"},
    )
    assert contract["label"] == "CONTRACT_LIKE"
    assert contract["standalone_trade_approval_allowed"] is False


def test_streams_registry_requires_webhook_signature_validation() -> None:
    registry = build_streams_registry(
        None, env={"MORALIS_STREAM_WEBHOOK_URL": "https://example.test/hook"}
    )
    assert registry["streams_configured"] is False
    assert registry["streams_ready"] is False
    ready = build_streams_registry(
        None,
        env={
            "MORALIS_STREAM_WEBHOOK_URL": "https://example.test/hook",
            "MORALIS_STREAM_WEBHOOK_SECRET": "present",
            "MORALIS_STREAM_SIGNATURE_VALIDATED": "true",
        },
    )
    assert ready["streams_configured"] is True
    assert ready["streams_ready"] is True


def test_moralis_feature_bridge_missing_data_uses_missing_mask_not_zero_fill() -> None:
    payload = build_moralis_feature_payload(
        symbol="BTCUSDT",
        token_map_count=1,
        wallet_watchlist_count=0,
        actual_payload_present=False,
        features={"moralis_exchange_inflow_usd": 123},
    )
    assert payload["features"] == {}
    assert payload["missing_mask_true"] is True
    assert payload["missing_feature_flags"]
    assert payload["stale_feature_flags"] == []
    assert payload["schema_version"] == "moralis_feature_bridge_v1"
    assert payload["moralis_can_approve_trade_alone"] is False


def test_moralis_feature_bridge_status_carries_counts_and_masks() -> None:
    redis_client = FakeRedis()
    payload = publish_moralis_feature_payload(
        redis_client,
        symbol="BTCUSDT",
        timeframe="1m",
        features={},
        token_map_count=9,
        wallet_watchlist_count=0,
        actual_payload_present=False,
    )

    status = json.loads(redis_client.data["v2:provider:moralis:feature_bridge_status"])
    assert payload["status"] == "ISOLATED_BY_POLICY"
    assert payload["trainer_admission_status"] == "ISOLATED_BY_POLICY"
    assert payload["source_status"] == "CONFIGURED_NO_WATCHLIST"
    assert status["token_map_count"] == 9
    assert status["wallet_watchlist_count"] == 0
    assert status["feature_count"] == 0
    assert status["required_feature_count"] == len(FEATURE_NAMES)
    assert status["missing_mask_true"] is True
    assert status["stale_mask_true"] is False
    assert status["available_at"] == payload["available_at"]
    assert payload["generated_at"] <= payload["available_at"]
    assert payload["feature_cutoff"] is None
    assert "v2:provider:moralis:symbol_score:BTCUSDT" in redis_client.data
    assert "v2:altdata:symbol_score:BTCUSDT" not in redis_client.data


def test_complete_source_payload_remains_observable_but_trainer_masked() -> None:
    features = {name: 1.0 for name in FEATURE_NAMES}
    payload = build_moralis_feature_payload(
        symbol="BTCUSDT",
        token_map_count=1,
        wallet_watchlist_count=1,
        actual_payload_present=True,
        event_time="2026-07-08T12:00:00Z",
        feature_cutoff="2026-07-08T12:00:00Z",
        features=features,
    )

    assert payload["source_actual_payload_present"] is True
    assert payload["source_feature_count"] == len(features)
    assert payload["source_missing_feature_flags"] == []
    assert payload["source_feature_bridge_ready"] is True
    assert payload["source_status"] == "READY"
    assert payload["source_dashboard_color"] == "GREEN"
    assert payload["features"] == {}
    assert payload["feature_count"] == 0
    assert payload["feature_bridge_ready"] is False
    assert payload["dashboard_color"] == "GRAY"
    assert payload["missing_feature_flags"] == list(FEATURE_NAMES)
    assert payload["decision_time_safe"] is False
    assert payload["trainer_decision_time_safe"] is False
    assert payload["temporal_contract_valid"] is False
    assert payload["source_temporal_contract_valid"] is True
    assert payload["event_time"] <= payload["feature_cutoff"]
    assert payload["feature_cutoff"] <= payload["generated_at"]
    assert payload["generated_at"] <= payload["available_at"]


def test_environment_cannot_bypass_receipt_gated_trainer_isolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MORALIS_TRAINER_ISOLATION", "0")
    redis_client = FakeRedis()

    payload = publish_moralis_feature_payload(
        redis_client,
        symbol="BTCUSDT",
        timeframe="1m",
        features={name: 1.0 for name in FEATURE_NAMES},
        token_map_count=1,
        wallet_watchlist_count=1,
        actual_payload_present=True,
        event_time="2026-07-08T11:59:58Z",
        feature_cutoff="2026-07-08T12:00:00Z",
    )
    status = json.loads(redis_client.data["v2:provider:moralis:feature_bridge_status"])

    assert payload["trainer_isolation_active"] is True
    assert payload["trainer_admission_status"] == "ISOLATED_BY_POLICY"
    assert payload["consumer_receipts_bound"] is False
    assert payload["features"] == {}
    assert payload["feature_count"] == 0
    assert payload["actual_payload_present"] is False
    assert payload["decision_time_safe"] is False
    assert status["trainer_consumption"] is False
    assert status["provider_tensor_consumption"] is False
    assert status["ppo_consumption"] is False
    assert status["masa_consumption"] is False
    assert status["risk_consumption"] is False
    assert status["orchestrator_consumption"] is False
    assert status["allocator_consumption"] is False
    assert status["paper_consumption"] is False
    assert status["feedback_attribution"] is False


def test_implementation_flag_alone_cannot_bypass_missing_consumer_receipts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        moralis_feature_bridge,
        "MORALIS_TRAINER_CONSUMPTION_BOUND",
        True,
    )
    monkeypatch.setattr(
        moralis_feature_bridge,
        "MORALIS_CONSUMER_RECEIPTS_BOUND",
        False,
    )

    payload = build_moralis_feature_payload(
        symbol="BTCUSDT",
        features={name: 1.0 for name in FEATURE_NAMES},
        token_map_count=1,
        wallet_watchlist_count=1,
        actual_payload_present=True,
        event_time="2026-07-08T11:59:58Z",
        feature_cutoff="2026-07-08T12:00:00Z",
    )

    assert payload["trainer_isolation_active"] is True
    assert payload["trainer_consumption_prerequisites_bound"] is False
    assert payload["trainer_admission_status"] == "ISOLATED_BY_POLICY"
    assert payload["features"] == {}
    assert payload["actual_payload_present"] is False
    assert payload["decision_time_safe"] is False


def test_receipt_flag_alone_cannot_bypass_missing_implementation_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        moralis_feature_bridge,
        "MORALIS_TRAINER_CONSUMPTION_BOUND",
        False,
    )
    monkeypatch.setattr(
        moralis_feature_bridge,
        "MORALIS_CONSUMER_RECEIPTS_BOUND",
        True,
    )
    redis_client = FakeRedis()

    payload = publish_moralis_feature_payload(
        redis_client,
        symbol="BTCUSDT",
        features={name: 1.0 for name in FEATURE_NAMES},
        token_map_count=1,
        wallet_watchlist_count=1,
        actual_payload_present=True,
        event_time="2026-07-08T11:59:58Z",
        feature_cutoff="2026-07-08T12:00:00Z",
    )
    status = json.loads(redis_client.data["v2:provider:moralis:feature_bridge_status"])

    assert payload["source_temporal_contract_valid"] is True
    assert payload["temporal_contract_valid"] is False
    assert payload["trainer_temporal_contract_valid"] is False
    assert payload["trainer_consumption_prerequisites_bound"] is False
    assert payload["trainer_isolation_active"] is True
    assert payload["features"] == {}
    assert payload["actual_payload_present"] is False
    assert payload["decision_time_safe"] is False
    for consumer in (
        "trainer_consumption",
        "provider_tensor_consumption",
        "ppo_consumption",
        "masa_consumption",
        "risk_consumption",
        "orchestrator_consumption",
        "allocator_consumption",
        "paper_consumption",
        "live_dryrun_consumption",
        "feedback_attribution",
    ):
        assert status[consumer] is False


def test_upstream_temporal_rejection_evidence_survives_canonical_rebuild() -> None:
    reason = "token_transfers:EVENT_TIME_AFTER_OBSERVED_AT"
    payload = build_moralis_feature_payload(
        symbol="BTCUSDT",
        token_map_count=1,
        wallet_watchlist_count=1,
        upstream_temporal_rejection_reasons=[reason],
    )

    assert payload["source_temporal_contract_valid"] is False
    assert payload["source_temporal_rejection_reasons"] == [reason]
    assert payload["source_status"] == "TEMPORAL_CONTRACT_REJECTED"
    assert payload["event_time"] is None
    assert payload["feature_cutoff"] is None
    assert payload["available_at"] is None


def test_invalid_upstream_temporal_rejection_evidence_fails_closed_bounded() -> None:
    payload = build_moralis_feature_payload(
        symbol="BTCUSDT",
        upstream_temporal_rejection_reasons=["x" * 257],
    )

    assert payload["source_temporal_contract_valid"] is False
    assert payload["source_temporal_rejection_reasons"] == [
        "UPSTREAM_TEMPORAL_REJECTION_EVIDENCE_INVALID"
    ]


def test_endpoint_status_discards_expired_raw_transport_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client = FakeRedis()
    redis_client.set(
        "v2:provider:moralis:endpoint_status",
        json.dumps(
            {
                "endpoints": {
                    "token_transfers": {
                        "actual_payload_present": True,
                        "expires_at": "2026-07-08T12:00:00Z",
                    }
                }
            }
        ),
        ex=3600,
    )
    monkeypatch.setattr(
        moralis_publisher,
        "_now",
        lambda: "2026-07-08T12:01:00Z",
    )
    holders = next(
        spec for spec in moralis_endpoint_registry() if spec.endpoint_id == "token_holders"
    )

    publish_moralis_result(
        redis_client,
        env={"MORALIS_API_KEY": "secret"},
        spec=holders,
        chain="eth",
        symbol=None,
        token="0xtoken",  # noqa: S106 - fixture token identifier, not a credential
        http_status=None,
        payload=None,
        budget_status={"compute_budget": {"used_today": 50, "used_month": 50}},
        error_class="ConnectTimeout",
    )

    endpoint_status = json.loads(redis_client.data["v2:provider:moralis:endpoint_status"])
    assert set(endpoint_status["endpoints"]) == {"token_holders"}
    assert endpoint_status["actual_payload_endpoint_count"] == 0


def test_canonical_moralis_payload_stays_excluded_from_unified_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client = FakeRedis()
    clock = iter(("2026-07-08T12:00:01Z", "2026-07-08T12:00:02Z"))
    monkeypatch.setattr(moralis_feature_bridge, "_now", lambda: next(clock))

    published = publish_moralis_feature_payload(
        redis_client,
        symbol="BTCUSDT",
        timeframe="1m",
        features={name: 1.0 for name in FEATURE_NAMES},
        token_map_count=1,
        wallet_watchlist_count=1,
        actual_payload_present=True,
        event_time="2026-07-08T11:59:58Z",
        feature_cutoff="2026-07-08T12:00:00Z",
    )
    unified = build_unified_feature_payload(
        redis_client,
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time="2026-07-08T12:00:03Z",
    )

    assert published["temporal_contract_valid"] is False
    assert published["source_temporal_contract_valid"] is True
    assert published["event_time"] == "2026-07-08T11:59:58Z"
    assert published["feature_cutoff"] == "2026-07-08T12:00:00Z"
    assert published["generated_at"] == "2026-07-08T12:00:01Z"
    assert published["available_at"] == "2026-07-08T12:00:02Z"
    assert published["actual_payload_present"] is False
    assert published["features"] == {}
    assert published["decision_time_safe"] is False
    assert unified["point_in_time_safe"] is True
    assert unified["provider_feature_context"]["actual_provider_count"] == 0
    assert unified["provider_feature_context"]["temporal_contract_valid"] is False
    assert (
        unified["provider_feature_context"]["provider_payloads"]["moralis"][
            "excluded_from_features"
        ]
        is True
    )
    assert unified["features"] == {}


@pytest.mark.parametrize(
    ("override", "expected_reason"),
    (
        ({"event_time": "2026-07-08T11:59:59"}, "EVENT_TIME_NOT_STRICT_UTC"),
        ({"feature_cutoff": "not-a-time"}, "FEATURE_CUTOFF_NOT_STRICT_UTC"),
        ({"feature_cutoff": None}, "FEATURE_CUTOFF_MISSING"),
        ({"available_at": ""}, "AVAILABLE_AT_MISSING"),
        (
            {
                "event_time": "2026-07-08T12:00:01Z",
                "feature_cutoff": "2026-07-08T12:00:00Z",
            },
            "EVENT_TIME_AFTER_FEATURE_CUTOFF",
        ),
        (
            {"feature_cutoff": "2026-07-08T12:00:04Z"},
            "FEATURE_CUTOFF_AFTER_GENERATED_AT",
        ),
        ({"available_at": "2026-07-08T12:00:01Z"}, "GENERATED_AT_AFTER_AVAILABLE_AT"),
        (
            {"available_at": "2026-07-08T12:00:04Z"},
            "AVAILABLE_AT_AFTER_PUBLICATION_OBSERVED_AT",
        ),
    ),
)
def test_moralis_feature_payload_blocks_invalid_temporal_ordering(
    monkeypatch: pytest.MonkeyPatch,
    override: dict[str, str | None],
    expected_reason: str,
) -> None:
    clock = iter(("2026-07-08T12:00:02Z", "2026-07-08T12:00:03Z"))
    monkeypatch.setattr(moralis_feature_bridge, "_now", lambda: next(clock))
    clocks: dict[str, str | None] = {
        "event_time": "2026-07-08T11:59:59Z",
        "feature_cutoff": "2026-07-08T12:00:00Z",
    }
    clocks.update(override)

    payload = build_moralis_feature_payload(
        symbol="BTCUSDT",
        token_map_count=1,
        wallet_watchlist_count=1,
        actual_payload_present=True,
        features={name: 1.0 for name in FEATURE_NAMES},
        event_time=clocks["event_time"],
        feature_cutoff=clocks["feature_cutoff"],
        available_at=clocks.get("available_at"),
    )

    assert payload["status"] == "ISOLATED_BY_POLICY"
    assert payload["trainer_admission_status"] == "ISOLATED_BY_POLICY"
    assert payload["source_status"] == "TEMPORAL_CONTRACT_REJECTED"
    assert payload["temporal_contract_valid"] is False
    assert expected_reason in payload["temporal_rejection_reasons"]
    assert payload["actual_payload_present"] is False
    assert payload["features"] == {}
    assert payload["event_time"] is None
    assert payload["feature_cutoff"] is None
    assert payload["available_at"] is None


def test_metadata_validator_consumes_only_canonical_cache_and_promotes_source_bound_map() -> None:
    redis_client = FakeRedis()
    _row, token = _seed_link_token_map(redis_client)
    candidates = read_metadata_validation_tokens(redis_client)
    assert candidates == [
        {"symbol": "LINKUSDT", "chain": "eth", "token": token}
    ]
    assert read_pollable_tokens(redis_client) == []

    metadata_spec = next(
        spec for spec in moralis_endpoint_registry() if spec.endpoint_id == "token_metadata"
    )
    publish_moralis_result(
        redis_client,
        env={"MORALIS_API_KEY": "fixture-key"},
        spec=metadata_spec,
        chain="eth",
        symbol=None,
        token=token,
        http_status=200,
        payload=[
            {
                "address": token,
                "name": "Chainlink",
                "symbol": "LINK",
                "decimals": "18",
            }
        ],
        budget_status={"compute_budget": {"used_today": 10, "used_month": 10}},
    )

    report = metadata_validator.validate_token_map(
        redis_client,
        api_key="ignored-by-cache-only-validator",
    )

    assert report["verified_count"] == 1
    assert report["cache_pending_count"] == 0
    assert report["http_request_count"] == 0
    assert report["compute_units_spent"] == 0
    pollable = read_pollable_tokens(redis_client)
    assert len(pollable) == 1
    assert pollable[0]["symbol"] == "LINKUSDT"
    assert pollable[0]["token"] == token
    assert len(pollable[0]["metadata_envelope_sha256"]) == 64


@pytest.mark.parametrize(
    ("mapping_confidence", "expected_decimals", "provider_decimals"),
    [
        ("not-a-number", 18, "18"),
        (0.99, None, "not-an-int"),
    ],
)
def test_metadata_validator_quarantines_malformed_numeric_fields_without_crashing(
    mapping_confidence: object,
    expected_decimals: object,
    provider_decimals: object,
) -> None:
    redis_client = FakeRedis()
    row, token = _seed_link_token_map(redis_client)
    contract = row["contracts"][0]
    contract["mapping_confidence"] = mapping_confidence
    contract["decimals"] = expected_decimals
    redis_client.set("v2:moralis:token_map:LINKUSDT", json.dumps(row), ex=3600)
    metadata_spec = next(
        spec for spec in moralis_endpoint_registry() if spec.endpoint_id == "token_metadata"
    )
    publish_moralis_result(
        redis_client,
        env={"MORALIS_API_KEY": "fixture-key"},
        spec=metadata_spec,
        chain="eth",
        symbol=None,
        token=token,
        http_status=200,
        payload=[
            {
                "address": token,
                "name": "Chainlink",
                "symbol": "LINK",
                "decimals": provider_decimals,
            }
        ],
        budget_status={"compute_budget": {"used_today": 10, "used_month": 10}},
    )

    report = metadata_validator.validate_token_map(redis_client)

    assert report["pollable_count"] == 0
    assert read_pollable_tokens(redis_client) == []
    stored = json.loads(redis_client.data["v2:moralis:token_map:LINKUSDT"])
    stored_contract = stored["contracts"][0]
    assert stored_contract.get("tradeable_mapping_status") != "VERIFIED"
    assert stored_contract.get("metadata_verified") is not True


def test_flow_normalizer_rejects_category_and_substring_direction_inference() -> None:
    spec = next(
        item for item in moralis_endpoint_registry() if item.endpoint_id == "wallet_history"
    )

    normalized = normalize_moralis_payload(
        spec=spec,
        symbol="LINKUSDT",
        chain="eth",
        wallet=VALID_WALLET_ADDRESS,
        token=None,
        payload={
            "result": [
                {
                    "category": "mint",
                    "value_usd": 125.5,
                    "block_timestamp": "2026-07-08T12:00:00Z",
                },
                {
                    "direction": "without_context",
                    "value_usd": 77.0,
                    "block_timestamp": "2026-07-08T12:00:01Z",
                },
                {
                    "direction": "unknown",
                    "value_decimal": "999999",
                    "block_timestamp": "2026-07-08T12:00:02Z",
                },
            ]
        },
    )

    assert normalized["features"] == {}
    assert normalized["actual_payload_present"] is False


def test_canonical_cache_rejects_invalid_utf8_instead_of_replacement_hashing() -> None:
    redis_client = FakeRedis()
    token = VALID_TOKEN_ADDRESS
    now = "2026-07-19T12:00:00Z"
    envelope = {
        "schema_version": "moralis_normalized_payload_v1",
        "provider": "moralis",
        "endpoint_id": "token_metadata",
        "chain": "eth",
        "token": token,
        "provider_ready": True,
        "actual_payload_present": True,
        "subscription_status": "READY",
        "auth_status": "READY",
        "available_at": now,
        "ingested_at": now,
        "generated_at": now,
        "ttl_seconds": 86_400,
        "canonical_records": [
            {"address": token, "symbol": "LINK", "name": "BYTE_MARKER", "decimals": 18}
        ],
    }
    raw = json.dumps(envelope).encode("utf-8").replace(b"BYTE_MARKER", b"\x80")
    redis_client.data[f"v2:moralis:token_metadata:eth:{token}"] = raw  # type: ignore[assignment]

    result = read_canonical_records(
        redis_client,
        endpoint_id="token_metadata",
        chain="eth",
        token=token,
    )

    assert result.ready is False
    assert result.reason == "CACHE_UTF8_INVALID"
    assert result.envelope_sha256 is None


def test_mutable_redis_pollable_claim_without_full_provenance_is_rejected() -> None:
    redis_client = FakeRedis()
    redis_client.set(
        "v2:moralis:token_map_status",
        json.dumps({"symbols": ["RAW:UNVERIFIED"], "token_map_count": 1}),
    )
    redis_client.set(
        "v2:moralis:token_map:RAW:UNVERIFIED",
        json.dumps(
            {
                "symbol": "RAW:UNVERIFIED",
                "contracts": [
                    {
                        "chain": "eth",
                        "contract_address": VALID_TOKEN_ADDRESS,
                        "pollable": True,
                    }
                ],
            }
        ),
    )

    assert read_pollable_tokens(redis_client) == []
    assert read_metadata_validation_tokens(redis_client) == []


def test_wallet_reader_rederives_source_identity_and_classification(
    tmp_path,
) -> None:
    redis_client = FakeRedis()
    seed_path = tmp_path / "watchlist.json"
    seed_path.write_text(
        json.dumps(
            {
                "wallets": [
                    {
                        "chain": "eth",
                        "address": VALID_WALLET_ADDRESS,
                        "tier": "T0",
                        "source": "unit_fixture_source",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    publish_wallet_watchlist(redis_client, path=seed_path)
    assert read_wallet_watchlist(redis_client, path=seed_path) == [
        {
            "chain": "eth",
            "address": VALID_WALLET_ADDRESS,
            "tier": "T0",
            "source": "unit_fixture_source",
        }
    ]

    payload = json.loads(redis_client.data["v2:moralis:wallet_watchlist"])
    payload["rows"][0]["source"] = ""
    redis_client.set("v2:moralis:wallet_watchlist", json.dumps(payload))
    assert read_wallet_watchlist(redis_client, path=seed_path) == []

    forged_address = "0x" + ("3" * 40)
    forged = json.loads(redis_client.data["v2:moralis:wallet_watchlist"])
    forged["rows"][0] = {
        **forged["rows"][0],
        "address": forged_address,
        "source": "self_asserted_redis_source",
        "classification": classify_address(chain="eth", address=forged_address),
    }
    redis_client.set("v2:moralis:wallet_watchlist", json.dumps(forged))
    assert read_wallet_watchlist(redis_client, path=seed_path) == []
