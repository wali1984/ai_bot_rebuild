from __future__ import annotations

import hashlib
import hmac
import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
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
    classifier_source_event_id,
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
_CLASSIFIER_KEY = b"moralis-test-classifier-authentication-key"
_CLASSIFIER_KEY_ID = "moralis-test-key-2026-07"
_OBSERVED_AT = "2026-07-08T12:03:00Z"


class _FakePipeline:
    def __init__(self, redis_client: FakeRedis) -> None:
        self.redis_client = redis_client
        self.operations: list[tuple[str, str, int | None]] = []

    def set(self, key: str, value: str, ex: int | None = None) -> _FakePipeline:
        self.operations.append((key, value, ex))
        return self

    def execute(self) -> list[bool]:
        return [
            self.redis_client.set(key, value, ex=ttl)
            for key, value, ttl in self.operations
        ]


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

    def get(self, key: str):
        return self.data.get(key)

    def ttl(self, key: str) -> int:
        if key not in self.data:
            return -2
        return self.ttls.get(key, -1)

    def pipeline(self, *, transaction: bool) -> _FakePipeline:
        assert transaction is True
        return _FakePipeline(self)

    def scan_iter(self, pattern: str, count: int = 500):
        del count
        prefix = pattern.removesuffix("*")
        yield from (key for key in sorted(self.data) if key.startswith(prefix))

    def eval(self, script: str, numkeys: int, *args: object) -> int:
        assert numkeys == 1
        if "MORALIS_AGGREGATE_CAS_V1" not in script:
            raise AssertionError("unexpected Redis script")
        key, expected_exists, expected_raw, replacement, ttl = map(str, args)
        current = self.data.get(key)
        if expected_exists == "0":
            if current is not None:
                return 0
        elif current != expected_raw:
            return 0
        self.data[key] = replacement
        self.ttls[key] = int(ttl)
        return 1


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _iso_utc(value: str) -> str:
    return (
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        .astimezone(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _authenticated_classifier_receipts(
    rows: list[dict[str, Any]],
    *,
    endpoint_id: str = "token_transfers",
    request_target_kind: str = "token",
    request_target: str = "0xtoken",
    symbol: str = "BTCUSDT",
) -> dict[str, Any]:
    receipts: dict[str, Any] = {}
    for index, row in enumerate(rows):
        row.setdefault("log_index", index)
        event_id = classifier_source_event_id(row)
        address = row.get("exchange_counterparty_address")
        direction = row.get("exchange_flow_direction")
        event_time = row.get("block_timestamp")
        if not all(
            isinstance(value, str) and value for value in (event_id, address, direction, event_time)
        ):
            continue
        try:
            row_bytes = _canonical_json(row)
        except (TypeError, ValueError):
            continue
        material = {
            "schema_version": "moralis_authenticated_exchange_classifier_receipt_v2",
            "classifier_key_id": _CLASSIFIER_KEY_ID,
            "endpoint_id": endpoint_id,
            "request_target_kind": request_target_kind,
            "request_target": request_target.lower(),
            "symbol": symbol.upper(),
            "chain": "eth",
            "transaction_hash": str(row["transaction_hash"]).lower(),
            "log_index": str(row["log_index"]),
            "counterparty_address": address.lower(),
            "category": "exchange_hot_wallet",
            "flow_direction": direction.lower(),
            "source_event_id": event_id,
            "source_row_sha256": hashlib.sha256(row_bytes).hexdigest(),
            "classifier_event_time": _iso_utc(event_time),
            "classifier_registry_key": "v2:moralis:exchange_classifier_registry:test",
            "classifier_registry_version": "test-registry-v1",
            "classifier_registry_sha256": "a" * 64,
            "classifier_source_key": f"v2:moralis:classifier_source:test:{event_id}",
            "classifier_source_payload_sha256": "b" * 64,
            "authentication_method": "HMAC_SHA256",
        }
        material_bytes = _canonical_json(material)
        receipts[event_id] = {
            **material,
            "claim_sha256": hashlib.sha256(material_bytes).hexdigest(),
            "hmac_sha256": hmac.new(
                _CLASSIFIER_KEY,
                material_bytes,
                hashlib.sha256,
            ).hexdigest(),
        }
    return receipts


def _publish_fixture(redis_client: FakeRedis, **kwargs: Any) -> dict[str, Any]:
    payload = deepcopy(kwargs.get("payload"))
    rows = (
        [row for row in payload.get("result", []) if isinstance(row, dict)]
        if isinstance(payload, dict)
        else []
    )
    for index, row in enumerate(rows):
        if row.get("exchange_counterparty_address") and not row.get("transaction_hash"):
            row["transaction_hash"] = f"0xtest-event-{index}"
    kwargs["payload"] = payload
    return publish_moralis_result(
        redis_client,
        **kwargs,
        authenticated_classifier_receipts=_authenticated_classifier_receipts(
            rows,
            endpoint_id=str(kwargs["spec"].endpoint_id),
            request_target_kind=("wallet" if kwargs["spec"].requires_wallet else "token"),
            request_target=str(kwargs.get("wallet") or kwargs.get("token") or ""),
            symbol=str(kwargs.get("symbol") or ""),
        ),
        classifier_authentication_key=_CLASSIFIER_KEY,
        classifier_authentication_key_id=_CLASSIFIER_KEY_ID,
        observed_at=_OBSERVED_AT,
    )


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
    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(200, json={"usdPrice": 1.0})

    mixed_case_token = "0x" + ("Ab" * 20)
    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        response = MoralisClient(
            api_key="secret",  # noqa: S106 - non-secret test fixture
            limiter=limiter,  # type: ignore[arg-type]
            http_client=http_client,
        ).get(spec, chain=" Ethereum ", token=mixed_case_token)

    assert response.request_dispatched is True
    assert response.chain == "eth"
    assert response.token == mixed_case_token.lower()
    assert len(captured_requests) == 1
    requested_url = str(captured_requests[0].url)
    assert requested_url == (
        f"{MORALIS_DEEP_INDEX_BASE_URL}/erc20/{mixed_case_token.lower()}/price?chain=eth"
    )
    assert captured_requests[0].headers["accept-encoding"] == "identity"


def test_stream_endpoint_is_not_polled_by_client() -> None:
    spec = next(s for s in moralis_endpoint_registry() if s.endpoint_id == "streams")
    response = MoralisClient(api_key="secret").get(spec, chain="eth", symbol="BTCUSDT")
    assert response.error_class == "STREAM_ENDPOINT_NOT_POLLED"
    assert response.http_status is None


def test_publisher_writes_wallet_token_signal_feature_and_endpoint_status() -> None:
    r = FakeRedis()
    spec = next(s for s in moralis_endpoint_registry() if s.endpoint_id == "token_transfers")
    result = _publish_fixture(
        r,
        env={"MORALIS_API_KEY": "secret"},
        spec=spec,
        chain="eth",
        symbol="BTCUSDT",
        token="0xtoken",  # noqa: S106 - fixture token identifier, not a credential
        http_status=200,
        payload={
            "result": [
                {
                    "exchange_counterparty_classification": "EXCHANGE",
                    "exchange_counterparty_address": "0x" + ("1" * 40),
                    "exchange_flow_direction": "exchange_inflow",
                    "value_usd": 1200,
                    "block_timestamp": "2026-07-08T12:00:00Z",
                },
                {
                    "exchange_counterparty_classification": "EXCHANGE",
                    "exchange_counterparty_address": "0x" + ("2" * 40),
                    "exchange_flow_direction": "exchange_outflow",
                    "value_usd": 200,
                    "block_timestamp": "2026-07-08T12:00:01Z",
                },
            ]
        },
        budget_status={"compute_budget": {"used_today": 50, "used_month": 50}},
        token_map_count=1,
        wallet_watchlist_count=1,
    )
    assert result["source_observation_present"] is True
    assert result["actual_payload_present"] is False
    assert result["available_at"] is None
    assert result["provider_ready"] is False
    source_key = next(key for key in result["planned_keys"] if key.startswith("v2:moralis:raw:v2:"))
    assert source_key in r.data
    assert "v2:features:moralis:BTCUSDT:1m" in r.data
    assert "v2:smart_money:signals:BTCUSDT" in r.data
    endpoint_status = json.loads(r.data["v2:provider:moralis:endpoint_status"])
    assert endpoint_status["endpoints"]["token_transfers"]["actual_payload_present"] is False
    assert (
        endpoint_status["endpoints"]["token_transfers"]["raw_transport_actual_payload_present"]
        is True
    )
    feature_payload = json.loads(r.data["v2:features:moralis:BTCUSDT:1m"])
    assert feature_payload["schema_version"] == "moralis_feature_bridge_v2"
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
    assert health["source_health_status"] == "SOURCE_CLOCK_CONTRACT_REJECTED"
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

    _publish_fixture(
        r,
        env={"MORALIS_API_KEY": "secret"},
        spec=transfers,
        chain="eth",
        symbol="BTCUSDT",
        token="0xtoken",  # noqa: S106 - fixture token identifier, not a credential
        http_status=200,
        payload={
            "result": [
                {
                    "exchange_counterparty_classification": "EXCHANGE",
                    "exchange_counterparty_address": "0x" + ("1" * 40),
                    "exchange_flow_direction": "exchange_inflow",
                    "value_usd": 1200,
                    "block_timestamp": "2026-07-08T12:00:00Z",
                },
                {
                    "exchange_counterparty_classification": "EXCHANGE",
                    "exchange_counterparty_address": "0x" + ("2" * 40),
                    "exchange_flow_direction": "exchange_outflow",
                    "value_usd": 200,
                    "block_timestamp": "2026-07-08T12:00:01Z",
                },
            ]
        },
        budget_status={"compute_budget": {"used_today": 50, "used_month": 50}},
        token_map_count=1,
        wallet_watchlist_count=1,
    )
    _publish_fixture(
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
    assert aggregate_payload["actual_payload_endpoint_count"] == 0
    assert aggregate_payload["source_observation_endpoint_count"] == 2

    feature_payload = json.loads(r.data["v2:features:moralis:BTCUSDT:1m"])
    assert feature_payload["schema_version"] == "moralis_feature_bridge_v2"
    assert feature_payload["source_actual_payload_present"] is True
    assert feature_payload["source_feature_count"] == 3
    assert feature_payload["diagnostic_feature_count"] == 1
    assert feature_payload["actual_payload_present"] is False
    assert feature_payload["features"] == {}
    assert (
        aggregate_payload["endpoint_payloads"]["token_transfers"]["features"][
            "moralis_net_exchange_flow_usd"
        ]
        == 1000
    )
    assert (
        aggregate_payload["endpoint_payloads"]["wallet_swaps"]["diagnostic_features"][
            "moralis_observed_swap_buy_usd"
        ]
        == 800
    )
    assert "endpoint_payloads" not in feature_payload
    assert feature_payload["feature_bridge_ready"] is False
    assert "moralis_onchain_risk_score" in feature_payload["missing_feature_flags"]


def test_publisher_does_not_launder_invalid_prior_endpoint_clocks() -> None:
    redis_client = FakeRedis()
    redis_client.set(
        "v2:moralis:feature_aggregate:BTCUSDT:1m",
        _canonical_json(
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
        ).decode("utf-8"),
        ex=3600,
    )
    transfers = next(
        spec for spec in moralis_endpoint_registry() if spec.endpoint_id == "token_transfers"
    )

    _publish_fixture(
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
                    "exchange_counterparty_classification": "EXCHANGE",
                    "exchange_counterparty_address": "0x" + ("2" * 40),
                    "exchange_flow_direction": "exchange_outflow",
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
    assert aggregate["features"] == {}
    assert "moralis_observed_swap_buy_usd" not in aggregate["diagnostic_features"]
    assert "wallet_swaps:SOURCE_KEY_MISSING" in aggregate["endpoint_temporal_rejection_reasons"]


def test_publisher_blocks_later_future_row_hidden_behind_an_earlier_first_row() -> None:
    redis_client = FakeRedis()
    transfers = next(
        spec for spec in moralis_endpoint_registry() if spec.endpoint_id == "token_transfers"
    )

    result = _publish_fixture(
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
                    "exchange_counterparty_classification": "EXCHANGE",
                    "exchange_counterparty_address": "0x" + ("2" * 40),
                    "exchange_flow_direction": "exchange_outflow",
                    "value_usd": 800,
                    "block_timestamp": "2026-07-08T12:00:00Z",
                },
                {
                    "exchange_counterparty_classification": "EXCHANGE",
                    "exchange_counterparty_address": "0x" + ("2" * 40),
                    "exchange_flow_direction": "exchange_outflow",
                    "value_usd": 1200,
                    "block_timestamp": "2099-07-08T12:00:00Z",
                },
            ]
        },
        budget_status={"compute_budget": {"used_today": 50, "used_month": 50}},
        token_map_count=1,
        wallet_watchlist_count=1,
    )

    source_key = next(key for key in result["planned_keys"] if key.startswith("v2:moralis:raw:v2:"))
    source = json.loads(redis_client.data[source_key])
    canonical = json.loads(redis_client.data["v2:features:moralis:BTCUSDT:1m"])
    aggregate = json.loads(redis_client.data["v2:moralis:feature_aggregate:BTCUSDT:1m"])
    endpoint = aggregate["endpoint_payloads"]["token_transfers"]
    assert canonical["actual_payload_present"] is False
    assert canonical["heartbeat_only"] is True
    assert canonical["features"] == {}
    assert canonical["source_temporal_contract_valid"] is False
    assert canonical["event_time"] is None
    assert canonical["feature_cutoff"] is None
    assert endpoint["features"]["moralis_exchange_outflow_usd"] == 800
    assert endpoint["event_time"] == "2026-07-08T12:00:00.000000Z"
    assert source["normalization_rejection_reasons"] == [
        "ROW_1:CONTRIBUTOR_EVENT_TIME_AFTER_NORMALIZATION"
    ]
    evidence = endpoint["feature_evidence"]["moralis_exchange_outflow_usd"]
    assert evidence["contributing_row_count"] == 1
    assert evidence["contributing_rows"][0]["row_index"] == 0
    assert aggregate["actual_payload_endpoint_count"] == 0
    health = json.loads(redis_client.data["v2:provider:moralis:health"])
    assert health["source_health_status"] != "READY"
    assert health["source_temporal_contract_valid"] is False
    assert health["trusted_source_actual_endpoint_count"] == 0
    assert health["raw_transport_actual_endpoint_count"] == 1


def test_publisher_uses_latest_clock_across_out_of_order_contributing_rows() -> None:
    redis_client = FakeRedis()
    transfers = next(
        spec for spec in moralis_endpoint_registry() if spec.endpoint_id == "token_transfers"
    )

    _publish_fixture(
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
                    "exchange_counterparty_classification": "EXCHANGE",
                    "exchange_counterparty_address": "0x" + ("2" * 40),
                    "exchange_flow_direction": "exchange_outflow",
                    "value_usd": 300,
                    "block_timestamp": "2026-07-08T12:02:00Z",
                },
                {
                    "exchange_counterparty_classification": "EXCHANGE",
                    "exchange_counterparty_address": "0x" + ("2" * 40),
                    "exchange_flow_direction": "exchange_outflow",
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

    assert endpoint["event_time"] == "2026-07-08T12:02:00.000000Z"
    assert endpoint["feature_cutoff"] == "2026-07-08T12:02:00.000000Z"
    assert endpoint["features"]["moralis_exchange_outflow_usd"] == 1500


def test_publisher_rejects_clockless_row_without_erasing_valid_contributor() -> None:
    redis_client = FakeRedis()
    transfers = next(
        spec for spec in moralis_endpoint_registry() if spec.endpoint_id == "token_transfers"
    )

    result = _publish_fixture(
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
                    "exchange_counterparty_classification": "EXCHANGE",
                    "exchange_counterparty_address": "0x" + ("2" * 40),
                    "exchange_flow_direction": "exchange_outflow",
                    "value_usd": 300,
                    "block_timestamp": "2026-07-08T12:02:00Z",
                },
                {
                    "exchange_counterparty_classification": "EXCHANGE",
                    "exchange_counterparty_address": "0x" + ("2" * 40),
                    "exchange_flow_direction": "exchange_outflow",
                    "value_usd": 1200,
                },
            ]
        },
        budget_status={"compute_budget": {"used_today": 50, "used_month": 50}},
        token_map_count=1,
        wallet_watchlist_count=1,
    )

    aggregate = json.loads(redis_client.data["v2:moralis:feature_aggregate:BTCUSDT:1m"])
    source_key = next(key for key in result["planned_keys"] if key.startswith("v2:moralis:raw:v2:"))
    source = json.loads(redis_client.data[source_key])
    endpoint = aggregate["endpoint_payloads"]["token_transfers"]

    assert aggregate["actual_payload_endpoint_count"] == 0
    assert set(aggregate["endpoint_payloads"]) == {"token_transfers"}
    assert endpoint["features"] == {"moralis_exchange_outflow_usd": 300.0}
    assert endpoint["event_time"] == "2026-07-08T12:02:00.000000Z"
    assert source["normalization_rejection_reasons"] == [
        "ROW_1:AUTHENTICATED_EXCHANGE_CLASSIFIER_RECEIPT_MISSING_OR_INVALID"
    ]


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
    assert endpoint_status["actual_payload_endpoint_count"] == 0
    assert endpoint_status["raw_transport_actual_endpoint_count"] == 1
    health = json.loads(r.data["v2:provider:moralis:health"])
    assert health["status"] == "ISOLATED_BY_POLICY"
    assert health["actual_payload_count_5m"] == 0
    assert health["source_health_status"] == "DEGRADED"
    assert health["source_status"] is None
    assert health["source_dashboard_color"] == "GRAY"
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
    assert payload["schema_version"] == "moralis_feature_bridge_v2"
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
    assert status["required_feature_count"] == 0
    assert status["optional_feature_count"] == len(FEATURE_NAMES)
    assert status["missing_mask_true"] is True
    assert status["stale_mask_true"] is False
    assert status["available_at"] is None
    assert payload["available_at"] is None
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
        ingested_at="2026-07-08T12:00:01Z",
        features=features,
    )

    assert payload["source_actual_payload_present"] is True
    assert payload["source_feature_count"] == len(features)
    assert payload["source_missing_feature_flags"] == []
    assert payload["source_feature_bridge_ready"] is False
    assert payload["source_status"] == "NON_AUTHORITATIVE_POSTCOMMIT_RECEIPT_UNBOUND"
    assert payload["source_dashboard_color"] == "YELLOW"
    assert payload["features"] == {}
    assert payload["feature_count"] == 0
    assert payload["feature_bridge_ready"] is False
    assert payload["dashboard_color"] == "GRAY"
    assert payload["missing_feature_flags"] == list(FEATURE_NAMES)
    assert payload["missing_mask_true"] is True
    assert payload["decision_time_safe"] is False
    assert payload["trainer_decision_time_safe"] is False
    assert payload["temporal_contract_valid"] is False
    assert payload["source_temporal_contract_valid"] is False
    assert payload["source_clock_order_valid"] is True
    assert payload["event_time"] <= payload["feature_cutoff"]
    assert payload["feature_cutoff"] <= payload["ingested_at"]
    assert payload["ingested_at"] <= payload["generated_at"]
    assert payload["available_at"] is None


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

    assert payload["source_temporal_contract_valid"] is False
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
    assert reason in payload["source_temporal_rejection_reasons"]
    assert "POSTCOMMIT_RECEIPT_UNBOUND" in payload["source_temporal_rejection_reasons"]
    assert payload["source_status"] == "SOURCE_CLOCK_CONTRACT_REJECTED"
    assert payload["event_time"] is None
    assert payload["feature_cutoff"] is None
    assert payload["available_at"] is None


def test_invalid_upstream_temporal_rejection_evidence_fails_closed_bounded() -> None:
    payload = build_moralis_feature_payload(
        symbol="BTCUSDT",
        upstream_temporal_rejection_reasons=["x" * 257],
    )

    assert payload["source_temporal_contract_valid"] is False
    assert (
        "UPSTREAM_TEMPORAL_REJECTION_EVIDENCE_INVALID"
        in payload["source_temporal_rejection_reasons"]
    )
    assert "POSTCOMMIT_RECEIPT_UNBOUND" in payload["source_temporal_rejection_reasons"]


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
    monkeypatch.setattr(moralis_feature_bridge, "_now", lambda: "2026-07-08T12:00:01Z")

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
        ingested_at="2026-07-08T12:00:00.500000Z",
    )
    unified = build_unified_feature_payload(
        redis_client,
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time="2026-07-08T12:00:03Z",
    )

    assert published["temporal_contract_valid"] is False
    assert published["source_temporal_contract_valid"] is False
    assert published["source_clock_order_valid"] is True
    assert published["event_time"] == "2026-07-08T11:59:58.000000Z"
    assert published["feature_cutoff"] == "2026-07-08T12:00:00.000000Z"
    assert published["generated_at"] == "2026-07-08T12:00:01.000000Z"
    assert published["available_at"] is None
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
    ("override", "expected_reason", "expected_source_status"),
    (
        (
            {"event_time": "2026-07-08T11:59:59"},
            "EVENT_TIME_NOT_STRICT_UTC",
            "SOURCE_CLOCK_CONTRACT_REJECTED",
        ),
        (
            {"feature_cutoff": "not-a-time"},
            "FEATURE_CUTOFF_NOT_STRICT_UTC",
            "SOURCE_CLOCK_CONTRACT_REJECTED",
        ),
        (
            {"feature_cutoff": None},
            "FEATURE_CUTOFF_MISSING",
            "SOURCE_CLOCK_CONTRACT_REJECTED",
        ),
        (
            {"ingested_at": None},
            "INGESTED_AT_MISSING",
            "SOURCE_CLOCK_CONTRACT_REJECTED",
        ),
        (
            {
                "event_time": "2026-07-08T12:00:01Z",
                "feature_cutoff": "2026-07-08T12:00:00Z",
            },
            "EVENT_TIME_AFTER_FEATURE_CUTOFF",
            "SOURCE_CLOCK_CONTRACT_REJECTED",
        ),
        (
            {"feature_cutoff": "2026-07-08T12:00:01.500000Z"},
            "FEATURE_CUTOFF_AFTER_INGESTED_AT",
            "SOURCE_CLOCK_CONTRACT_REJECTED",
        ),
        (
            {"ingested_at": "2026-07-08T12:00:03Z"},
            "INGESTED_AT_AFTER_GENERATED_AT",
            "SOURCE_CLOCK_CONTRACT_REJECTED",
        ),
        (
            {"available_at": "2026-07-08T12:00:04Z"},
            "SUPPLIED_AVAILABLE_AT_IGNORED_NO_POSTCOMMIT_RECEIPT",
            "NON_AUTHORITATIVE_POSTCOMMIT_RECEIPT_UNBOUND",
        ),
    ),
)
def test_moralis_feature_payload_blocks_invalid_temporal_ordering(
    monkeypatch: pytest.MonkeyPatch,
    override: dict[str, str | None],
    expected_reason: str,
    expected_source_status: str,
) -> None:
    monkeypatch.setattr(moralis_feature_bridge, "_now", lambda: "2026-07-08T12:00:02Z")
    clocks: dict[str, str | None] = {
        "event_time": "2026-07-08T11:59:59Z",
        "feature_cutoff": "2026-07-08T12:00:00Z",
        "ingested_at": "2026-07-08T12:00:01Z",
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
        ingested_at=clocks["ingested_at"],
        available_at=clocks.get("available_at"),
    )

    assert payload["status"] == "ISOLATED_BY_POLICY"
    assert payload["trainer_admission_status"] == "ISOLATED_BY_POLICY"
    assert payload["source_status"] == expected_source_status
    assert payload["temporal_contract_valid"] is False
    assert expected_reason in payload["temporal_rejection_reasons"]
    assert payload["actual_payload_present"] is False
    assert payload["features"] == {}
    if expected_source_status == "SOURCE_CLOCK_CONTRACT_REJECTED":
        assert payload["event_time"] is None
        assert payload["feature_cutoff"] is None
    assert payload["available_at"] is None


def test_metadata_validator_consumes_only_canonical_cache_and_promotes_source_bound_map() -> None:
    redis_client = FakeRedis()
    _row, token = _seed_link_token_map(redis_client)
    candidates = read_metadata_validation_tokens(redis_client)
    assert candidates == [{"symbol": "LINKUSDT", "chain": "eth", "token": token}]
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

    # The v2 cache receipt is source-only and can validate token metadata while
    # every trainer/trading authority remains false.
    assert report["verified_count"] == 1
    assert report["cache_pending_count"] == 0
    assert report["http_request_count"] == 0
    assert report["compute_units_spent"] == 0
    pollable = read_pollable_tokens(redis_client)
    assert len(pollable) == 1
    assert {name: pollable[0][name] for name in ("symbol", "chain", "token")} == {
        "symbol": "LINKUSDT",
        "chain": "eth",
        "token": token,
    }
    assert pollable[0]["metadata_available_at"] == ""
    assert pollable[0]["metadata_expires_at"]
    assert len(pollable[0]["metadata_envelope_sha256"]) == 64
    status = json.loads(redis_client.data["v2:moralis:token_map_status"])
    assert status["pollable_token_count"] == 1
    assert status["pollable_contract_count"] == 1
    assert status["manual_review_required_count"] == 0
    assert status["metadata_validation_required"] is False


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
    assert normalized["actual_payload_present"] is True
    assert normalized["semantic_payload_present"] is False


def test_canonical_cache_ignores_legacy_token_metadata_even_when_malformed() -> None:
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
    assert result.reason == "CACHE_MISSING"
    assert result.envelope_sha256 is None


def test_token_metadata_v2_cache_bootstrap_restart_partial_and_malformed_states() -> None:
    redis_client = FakeRedis()
    token = VALID_TOKEN_ADDRESS
    metadata_spec = next(
        spec for spec in moralis_endpoint_registry() if spec.endpoint_id == "token_metadata"
    )
    published = publish_moralis_result(
        redis_client,
        env={"MORALIS_API_KEY": "fixture-key"},
        spec=metadata_spec,
        chain="eth",
        token=token,
        symbol=None,
        http_status=200,
        payload=[
            {
                "address": token,
                "name": "Token",
                "symbol": "TOK",
                "decimals": "18",
            }
        ],
        budget_status={},
    )
    source_key = next(
        key for key in published["planned_keys"] if key.startswith("v2:moralis:raw:v2:")
    )
    manifest_key = next(
        key
        for key in published["planned_keys"]
        if key.startswith("v2:moralis:manifest:v2:token_metadata:")
    )
    index_key = f"v2:moralis:index:v2:token_metadata:eth:{token}"
    assert published["publication_acknowledged"] is True

    first = read_canonical_records(
        redis_client,
        endpoint_id="token_metadata",
        chain="eth",
        token=token,
    )
    assert first.ready is True
    assert first.reason == "READY"
    assert first.available_at is None
    assert first.records[0]["symbol"] == "TOK"

    immutable_keys = (source_key, manifest_key, index_key)
    values_before_duplicate = {key: redis_client.data[key] for key in immutable_keys}
    ttls_before_duplicate = {key: redis_client.ttls[key] for key in immutable_keys}
    duplicate = publish_moralis_result(
        redis_client,
        env={"MORALIS_API_KEY": "fixture-key"},
        spec=metadata_spec,
        chain="eth",
        token=token,
        symbol=None,
        http_status=200,
        payload=[
            {
                "address": token,
                "name": "Token",
                "symbol": "TOK",
                "decimals": "18",
            }
        ],
        budget_status={},
    )
    assert set(immutable_keys).issubset(set(duplicate["duplicate_keys"]))
    assert {key: redis_client.data[key] for key in immutable_keys} == values_before_duplicate
    assert {key: redis_client.ttls[key] for key in immutable_keys} == ttls_before_duplicate

    restarted = FakeRedis()
    restarted.data.update(redis_client.data)
    restarted.ttls.update(redis_client.ttls)
    after_restart = read_canonical_records(
        restarted,
        endpoint_id="token_metadata",
        chain="eth",
        token=token,
    )
    assert after_restart == first

    for missing_key, expected_reason in (
        (index_key, "CACHE_MISSING"),
        (manifest_key, "MANIFEST_CACHE_MISSING"),
        (source_key, "SOURCE_CACHE_MISSING"),
    ):
        partial = FakeRedis()
        partial.data.update(redis_client.data)
        partial.ttls.update(redis_client.ttls)
        partial.data.pop(missing_key)
        partial.ttls.pop(missing_key, None)
        held = read_canonical_records(
            partial,
            endpoint_id="token_metadata",
            chain="eth",
            token=token,
        )
        assert held.ready is False
        assert held.reason == expected_reason

    malformed = FakeRedis()
    malformed.data.update(redis_client.data)
    malformed.ttls.update(redis_client.ttls)
    malformed.data[index_key] = b'{"bad":"\x80"}'  # type: ignore[assignment]
    malformed_read = read_canonical_records(
        malformed,
        endpoint_id="token_metadata",
        chain="eth",
        token=token,
    )
    assert malformed_read.ready is False
    assert malformed_read.reason == "CACHE_UTF8_INVALID"

    unsafe_key = FakeRedis()
    unsafe_key.data.update(redis_client.data)
    unsafe_key.ttls.update(redis_client.ttls)
    unsafe_index = json.loads(unsafe_key.data[index_key])
    unsafe_index["unsafe\u202ekey"] = "value"
    unsafe_key.data[index_key] = _canonical_json(unsafe_index).decode("utf-8")
    unsafe_key_read = read_canonical_records(
        unsafe_key,
        endpoint_id="token_metadata",
        chain="eth",
        token=token,
    )
    assert unsafe_key_read.ready is False
    assert unsafe_key_read.reason == "CACHE_JSON_INVALID"

    tampered = FakeRedis()
    tampered.data.update(redis_client.data)
    tampered.ttls.update(redis_client.ttls)
    index_payload = json.loads(tampered.data[index_key])
    index_payload["cache_receipt"]["source_exact_readback_verified"] = False
    tampered.data[index_key] = _canonical_json(index_payload).decode("utf-8")
    tampered_read = read_canonical_records(
        tampered,
        endpoint_id="token_metadata",
        chain="eth",
        token=token,
    )
    assert tampered_read.ready is False
    assert tampered_read.reason == "CACHE_RECEIPT_INVALID"

    short_provenance = FakeRedis()
    short_provenance.data.update(redis_client.data)
    short_provenance.ttls.update(redis_client.ttls)
    short_provenance.ttls[source_key] = 1
    short_read = read_canonical_records(
        short_provenance,
        endpoint_id="token_metadata",
        chain="eth",
        token=token,
    )
    assert short_read.ready is False
    assert short_read.reason == "CACHE_PROVENANCE_TTL_SHORTER_THAN_INDEX_LIFETIME"

    class RedisWithoutTTL:
        def get(self, key: str) -> str | None:
            return redis_client.get(key)

    ttl_unverifiable = read_canonical_records(
        RedisWithoutTTL(),
        endpoint_id="token_metadata",
        chain="eth",
        token=token,
    )
    assert ttl_unverifiable.ready is False
    assert ttl_unverifiable.reason == "CACHE_PROVENANCE_TTL_READ_FAILED"

    authority_tampered = FakeRedis()
    authority_tampered.data.update(redis_client.data)
    authority_tampered.ttls.update(redis_client.ttls)
    authority_index = json.loads(authority_tampered.data[index_key])
    authority_index["publication_authority"] = True
    authority_tampered.data[index_key] = _canonical_json(authority_index).decode("utf-8")
    authority_read = read_canonical_records(
        authority_tampered,
        endpoint_id="token_metadata",
        chain="eth",
        token=token,
    )
    assert authority_read.ready is False
    assert authority_read.reason == "CACHE_AUTHORITY_SCOPE_INVALID"

    manifest_rewired = FakeRedis()
    manifest_rewired.data.update(redis_client.data)
    manifest_rewired.ttls.update(redis_client.ttls)
    alternate_manifest_key = "v2:moralis:manifest:v2:token_metadata:" + ("f" * 64)
    manifest_rewired.data[alternate_manifest_key] = manifest_rewired.data[manifest_key]
    manifest_rewired.ttls[alternate_manifest_key] = manifest_rewired.ttls[manifest_key]
    rewired_index = json.loads(manifest_rewired.data[index_key])
    rewired_index["manifest_key"] = alternate_manifest_key
    rewired_index["cache_receipt"]["manifest_key"] = alternate_manifest_key
    manifest_rewired.data[index_key] = _canonical_json(rewired_index).decode("utf-8")
    manifest_rewired_read = read_canonical_records(
        manifest_rewired,
        endpoint_id="token_metadata",
        chain="eth",
        token=token,
    )
    assert manifest_rewired_read.ready is False
    assert manifest_rewired_read.reason == "CACHE_RECEIPT_BINDING_INVALID"

    source_rewired = FakeRedis()
    source_rewired.data.update(redis_client.data)
    source_rewired.ttls.update(redis_client.ttls)
    alternate_source_key = source_key.replace(
        source_key.split(":")[-2],
        "0" * 64,
    )
    source_rewired.data[alternate_source_key] = source_rewired.data[source_key]
    source_rewired.ttls[alternate_source_key] = source_rewired.ttls[source_key]
    rewired_manifest = json.loads(source_rewired.data[manifest_key])
    rewired_manifest["source_key"] = alternate_source_key
    rewired_manifest_bytes = _canonical_json(rewired_manifest)
    source_rewired.data[manifest_key] = rewired_manifest_bytes.decode("utf-8")
    rewired_manifest_sha = hashlib.sha256(rewired_manifest_bytes).hexdigest()
    rewired_index = json.loads(source_rewired.data[index_key])
    rewired_index["source_key"] = alternate_source_key
    rewired_index["manifest_sha256"] = rewired_manifest_sha
    rewired_index["cache_receipt"]["source_key"] = alternate_source_key
    rewired_index["cache_receipt"]["manifest_sha256"] = rewired_manifest_sha
    source_rewired.data[index_key] = _canonical_json(rewired_index).decode("utf-8")
    source_rewired_read = read_canonical_records(
        source_rewired,
        endpoint_id="token_metadata",
        chain="eth",
        token=token,
    )
    assert source_rewired_read.ready is False
    assert source_rewired_read.reason == "SOURCE_KEY_IDENTITY_MISMATCH"


@pytest.mark.parametrize(
    "corruption",
    (
        "authority",
        "admitted_count",
        "consumption_claim",
        "receipt",
        "source_binding",
        "short_index_ttl",
    ),
)
def test_token_metadata_duplicate_retry_repairs_invalid_index_contract(
    corruption: str,
) -> None:
    redis_client = FakeRedis()
    token = VALID_TOKEN_ADDRESS
    metadata_spec = next(
        spec for spec in moralis_endpoint_registry() if spec.endpoint_id == "token_metadata"
    )
    call = {
        "env": {"MORALIS_API_KEY": "fixture-key"},
        "spec": metadata_spec,
        "chain": "eth",
        "token": token,
        "symbol": None,
        "http_status": 200,
        "payload": [
            {
                "address": token,
                "name": "Token",
                "symbol": "TOK",
                "decimals": "18",
            }
        ],
        "budget_status": {},
    }
    first = publish_moralis_result(
        redis_client,
        observed_at="2026-07-08T12:03:00Z",
        **call,
    )
    index_key = f"v2:moralis:index:v2:token_metadata:eth:{token}"
    assert first["publication_acknowledged"] is True

    if corruption == "short_index_ttl":
        redis_client.ttls[index_key] = 1
    else:
        index = json.loads(redis_client.data[index_key])
        if corruption == "authority":
            index["publication_authority"] = True
        elif corruption == "admitted_count":
            index["admitted_feature_count"] = 1
        elif corruption == "consumption_claim":
            index["trainer_consumption"] = True
        elif corruption == "receipt":
            index["cache_receipt"]["source_exact_readback_verified"] = False
        else:
            index["source_key"] = index["source_key"].replace(
                index["source_key"].split(":")[-2],
                "0" * 64,
            )
        redis_client.data[index_key] = _canonical_json(index).decode("utf-8")

    repaired = publish_moralis_result(
        redis_client,
        observed_at="2026-07-08T12:03:01Z",
        **call,
    )
    cache = read_canonical_records(
        redis_client,
        endpoint_id="token_metadata",
        chain="eth",
        token=token,
        observed_at=datetime(2026, 7, 8, 12, 3, 2, tzinfo=UTC),
    )
    repaired_index = json.loads(redis_client.data[index_key])

    assert repaired["publication_acknowledged"] is True
    assert index_key in repaired["keys_written"]
    assert index_key not in repaired["duplicate_keys"]
    assert cache.ready is True
    assert cache.reason == "READY"
    assert repaired_index["publication_authority"] is False
    assert repaired_index["postcommit_receipt_bound"] is False
    assert repaired_index["cache_receipt"]["source_exact_readback_verified"] is True
    assert repaired_index["cache_receipt"]["manifest_exact_readback_verified"] is True
    assert repaired_index["admitted_feature_count"] == 0
    assert repaired_index["trainer_authority"] is False
    assert repaired_index["live_authority"] is False
    assert repaired_index.get("trainer_consumption") is not True


def test_token_metadata_publisher_and_reader_share_canonical_chain_aliases() -> None:
    redis_client = FakeRedis()
    token = VALID_TOKEN_ADDRESS
    metadata_spec = next(
        spec for spec in moralis_endpoint_registry() if spec.endpoint_id == "token_metadata"
    )

    published = publish_moralis_result(
        redis_client,
        env={"MORALIS_API_KEY": "fixture-key"},
        spec=metadata_spec,
        chain="ethereum",
        token=token,
        symbol=None,
        http_status=200,
        payload=[
            {
                "address": token,
                "name": "Token",
                "symbol": "TOK",
                "decimals": "18",
            }
        ],
        budget_status={},
        observed_at="2026-07-08T12:03:00Z",
    )
    canonical_index_key = f"v2:moralis:index:v2:token_metadata:eth:{token}"
    alias_read = read_canonical_records(
        redis_client,
        endpoint_id="token_metadata",
        chain="ethereum",
        token=token,
        observed_at=datetime(2026, 7, 8, 12, 3, 1, tzinfo=UTC),
    )
    canonical_read = read_canonical_records(
        redis_client,
        endpoint_id="token_metadata",
        chain="eth",
        token=token,
        observed_at=datetime(2026, 7, 8, 12, 3, 1, tzinfo=UTC),
    )

    assert published["publication_acknowledged"] is True
    assert canonical_index_key in published["planned_keys"]
    assert not any(":ethereum:" in key for key in published["planned_keys"])
    assert alias_read.ready is True
    assert canonical_read.ready is True
    assert alias_read == canonical_read
    assert alias_read.chain == "eth"


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
                "schema_version": "moralis_wallet_watchlist_seed_v1",
                "policy": {
                    "empty_watchlist_status": "CONFIGURED_NO_WATCHLIST",
                    "t0_max_wallets": 50,
                    "t1_max_wallets": 250,
                    "unknown_wallet_is_smart_money": False,
                },
                "wallets": [
                    {
                        "chain": "eth",
                        "address": VALID_WALLET_ADDRESS,
                        "tier": "T0",
                        "source": "unit_fixture_source",
                        "classification": "CANDIDATE_SMART_WALLET",
                        "verified_smart_wallet": False,
                        "added_utc": "2020-01-01T00:00:00Z",
                        "added_by": "v2_moralis_wallet_watchlist_bootstrap",
                    }
                ],
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
