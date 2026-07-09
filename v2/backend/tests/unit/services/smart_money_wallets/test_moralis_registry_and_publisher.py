from __future__ import annotations

import json

from v2.backend.app.services.smart_money_wallets.address_classifier import classify_address
from v2.backend.app.services.smart_money_wallets.client import MoralisClient
from v2.backend.app.services.smart_money_wallets.endpoint_registry import (
    moralis_endpoint_registry,
    registry_payload,
)
from v2.backend.app.services.smart_money_wallets.health import build_moralis_health
from v2.backend.app.services.smart_money_wallets.moralis_feature_bridge import (
    FEATURE_NAMES,
    build_moralis_feature_payload,
    publish_moralis_feature_payload,
)
from v2.backend.app.services.smart_money_wallets.publisher import publish_moralis_result
from v2.backend.app.services.smart_money_wallets.smart_wallet_scorer import score_wallet_candidate
from v2.backend.app.services.smart_money_wallets.streams_registry import build_streams_registry
from v2.backend.app.services.smart_money_wallets.token_contract_mapper import load_token_contract_map
from v2.backend.app.services.smart_money_wallets.wallet_watchlist import (
    TIER_LIMITS,
    load_wallet_watchlist_seed,
    wallet_watchlist_status,
)


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
        token="0xtoken",
        http_status=200,
        payload={"result": [{"direction": "out", "value_usd": 1200, "block_timestamp": "2026-07-08T12:00:00Z"}]},
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
    assert feature_payload["actual_payload_present"] is True
    assert feature_payload["feature_bridge_ready"] is False
    assert feature_payload["missing_feature_flags"]
    health = json.loads(r.data["v2:provider:moralis:health"])
    assert health["dashboard_color"] == "YELLOW"
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
        token="0xtoken",
        http_status=200,
        payload={"result": [{"direction": "out", "value_usd": 1200, "block_timestamp": "2026-07-08T12:00:00Z"}]},
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
        payload={"result": [{"side": "buy", "total_value_usd": 800, "block_timestamp": "2026-07-08T12:01:00Z"}]},
        budget_status={"compute_budget": {"used_today": 100, "used_month": 100}},
        token_map_count=1,
        wallet_watchlist_count=1,
    )

    aggregate_payload = json.loads(r.data["v2:moralis:feature_aggregate:BTCUSDT:1m"])
    assert set(aggregate_payload["endpoint_payloads"]) == {"token_transfers", "wallet_swaps"}
    assert aggregate_payload["actual_payload_endpoint_count"] == 2

    feature_payload = json.loads(r.data["v2:features:moralis:BTCUSDT:1m"])
    assert feature_payload["schema_version"] == "moralis_feature_bridge_v1"
    assert feature_payload["actual_payload_present"] is True
    assert feature_payload["features"]["moralis_net_exchange_flow_usd"] == 1200
    assert feature_payload["features"]["moralis_dex_buy_pressure_usd"] == 800
    assert "endpoint_payloads" not in feature_payload
    assert feature_payload["feature_bridge_ready"] is False
    assert "moralis_holder_count" in feature_payload["missing_feature_flags"]


def test_auth_backoff_status_stays_gray_not_degraded_yellow() -> None:
    r = FakeRedis()
    spec = next(s for s in moralis_endpoint_registry() if s.endpoint_id == "token_holders")

    result = publish_moralis_result(
        r,
        env={"MORALIS_API_KEY": "secret"},
        spec=spec,
        chain="eth",
        symbol="BTCUSDT",
        token="0xtoken",
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


def test_health_stays_green_when_actual_endpoint_exists_and_optional_endpoint_degrades() -> None:
    r = FakeRedis()
    transfers = next(s for s in moralis_endpoint_registry() if s.endpoint_id == "token_transfers")
    swaps = next(s for s in moralis_endpoint_registry() if s.endpoint_id == "wallet_swaps")

    publish_moralis_result(
        r,
        env={"MORALIS_API_KEY": "secret"},
        spec=transfers,
        chain="eth",
        symbol="BTCUSDT",
        token="0xtoken",
        http_status=200,
        payload={"result": [{"direction": "out", "value_usd": 1200, "block_timestamp": "2026-07-08T12:00:00Z"}]},
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
    assert health["status"] == "PARTIAL_REQUIRED_FEATURES_MISSING"
    assert health["actual_payload_count_5m"] == 1
    assert health["dashboard_color"] == "YELLOW"


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


def test_wallet_watchlist_seed_bootstraps_candidate_rows_with_tier_limits() -> None:
    rows = load_wallet_watchlist_seed()
    status = wallet_watchlist_status(rows, source_path="v2/config/moralis/wallet_watchlist_seed.yaml")

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
    registry = build_streams_registry(None, env={"MORALIS_STREAM_WEBHOOK_URL": "https://example.test/hook"})
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
        available_at="2026-07-09T01:00:00Z",
        event_time="2026-07-09T01:00:00Z",
    )

    status = json.loads(redis_client.data["v2:provider:moralis:feature_bridge_status"])
    assert payload["status"] == "CONFIGURED_NO_WATCHLIST"
    assert status["token_map_count"] == 9
    assert status["wallet_watchlist_count"] == 0
    assert status["feature_count"] == 0
    assert status["required_feature_count"] == len(FEATURE_NAMES)
    assert status["missing_mask_true"] is True
    assert status["stale_mask_true"] is False
    assert status["available_at"] == "2026-07-09T01:00:00Z"
    assert "v2:provider:moralis:symbol_score:BTCUSDT" in redis_client.data
    assert "v2:altdata:symbol_score:BTCUSDT" not in redis_client.data


def test_moralis_feature_bridge_full_payload_is_green_only_with_required_features() -> None:
    features = {name: 1.0 for name in FEATURE_NAMES}
    payload = build_moralis_feature_payload(
        symbol="BTCUSDT",
        token_map_count=1,
        wallet_watchlist_count=1,
        actual_payload_present=True,
        event_time="2026-07-08T12:00:00Z",
        available_at="2026-07-08T12:00:01Z",
        features=features,
    )

    assert payload["features"] == features
    assert payload["feature_bridge_ready"] is True
    assert payload["dashboard_color"] == "GREEN"
    assert payload["missing_feature_flags"] == []
    assert payload["decision_time_safe"] is True
