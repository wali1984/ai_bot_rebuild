from __future__ import annotations

import json

from v2.backend.app.services.provider_features import (
    build_provider_actual_data_panel,
    build_provider_consumer_context,
    endpoint_to_feature_mapping,
    provider_redis_key_contract,
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

    def ttl(self, key: str) -> int:
        if key not in self.data:
            return -2
        return self.ttls.get(key, -1)


def test_provider_redis_key_contract_names_required_keys() -> None:
    contract = provider_redis_key_contract()
    assert contract["coinglass"]["features"] == "v2:features:coinglass:{symbol}:{timeframe}"
    assert contract["moralis"]["smart_money_signals"] == "v2:smart_money:signals:{symbol}"
    assert contract["heartbeat_only_green_allowed"] is False


def test_endpoint_to_feature_mapping_has_cadence_and_budgets() -> None:
    mapping = endpoint_to_feature_mapping()
    funding = mapping["coinglass"]["funding_rate"]
    transfers = mapping["moralis"]["token_transfers"]
    streams = mapping["moralis"]["streams"]
    assert funding["request_budget_per_minute"] > 0
    assert funding["cadence_seconds"]["top_symbols"] >= 60
    assert transfers["compute_unit_cost"] > 0
    assert streams["stream_based"] is True
    assert mapping["moralis_every_symbol_every_minute_allowed"] is False


def test_bridge_maps_actual_coinglass_payload_to_tensor_features() -> None:
    r = FakeRedis()
    r.set(
        "v2:features:coinglass:BTCUSDT:1m",
        json.dumps(
            {
                "subscription_status": "READY",
                "actual_payload_present": True,
                "heartbeat_only": False,
                "available_at": "2026-07-08T12:00:00Z",
                "feature_cutoff": "2026-07-08T11:59:00Z",
                "features": {
                    "coinglass_funding_rate": 0.0001,
                    "coinglass_open_interest_usd": 1000000,
                },
            }
        ),
        ex=180,
    )
    context = build_provider_consumer_context(
        r,
        role="trainer",
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time="2026-07-08T12:01:00Z",
    )
    assert context["core_system_blocked"] is False
    assert context["provider_features"]["funding_rate"] == 0.0001
    assert context["payloads_for_tensor"]["open_interest"]["open_interest"] == 1000000


def test_bridge_maps_required_moralis_feature_names_to_tensor_context() -> None:
    r = FakeRedis()
    r.set(
        "v2:features:moralis:BTCUSDT:1m",
        json.dumps(
            {
                "schema_version": "moralis_feature_bridge_v1",
                "status": "READY",
                "dashboard_color": "GREEN",
                "feature_bridge_ready": True,
                "actual_payload_present": True,
                "heartbeat_only": False,
                "available_at": "2026-07-08T12:00:00Z",
                "feature_cutoff": "2026-07-08T11:59:00Z",
                "features": {
                    "moralis_whale_net_flow_usd": 1200,
                    "moralis_net_exchange_flow_usd": -700,
                    "moralis_dex_flow_imbalance_usd": 250,
                    "moralis_top_holder_concentration": 0.42,
                    "moralis_holder_count": 12345,
                    "moralis_holder_delta": 12,
                    "moralis_onchain_risk_score": 0.08,
                },
            }
        ),
        ex=300,
    )

    context = build_provider_consumer_context(
        r,
        role="trainer",
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time="2026-07-08T12:01:00Z",
    )

    assert context["core_system_blocked"] is False
    assert context["provider_features"]["smart_money_whale_net_flow_usd"] == 1200
    assert context["provider_features"]["token_holder_top_concentration"] == 0.42
    assert context["provider_features"]["token_holder_count"] == 12345
    assert context["provider_features"]["token_holder_delta"] == 12
    assert context["provider_features"]["onchain_risk_score"] == 0.08
    assert context["payloads_for_tensor"]["smart_money"]["onchain_risk_score"] == 0.08


def test_bridge_excludes_future_leaking_provider_features() -> None:
    r = FakeRedis()
    r.set(
        "v2:features:coinglass:BTCUSDT:1m",
        json.dumps(
            {
                "subscription_status": "READY",
                "actual_payload_present": True,
                "heartbeat_only": False,
                "available_at": "2026-07-08T12:05:00Z",
                "feature_cutoff": "2026-07-08T12:05:00Z",
                "features": {"coinglass_funding_rate": 0.1},
            }
        ),
        ex=180,
    )
    context = build_provider_consumer_context(
        r,
        role="risk",
        symbol="BTCUSDT",
        decision_time="2026-07-08T12:00:00Z",
    )
    assert "funding_rate" not in context["provider_features"]
    assert context["point_in_time_violations"]
    assert context["core_system_blocked"] is False


def test_actual_data_panel_does_not_mark_heartbeat_only_green() -> None:
    r = FakeRedis()
    r.set(
        "v2:features:moralis:BTCUSDT:1m",
        json.dumps(
            {
                "subscription_status": "READY",
                "actual_payload_present": False,
                "heartbeat_only": True,
                "features": {},
            }
        ),
        ex=300,
    )
    panel = build_provider_actual_data_panel(r, symbol="BTCUSDT", timeframe="1m")
    assert panel["moralis"]["heartbeat_only"] is True
    assert panel["moralis"]["dashboard_color"] != "GREEN"
    assert panel["optional_provider_failures_core_blocking"] is False
