from __future__ import annotations

import json

import pytest

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
    assert context["available_at"] == "2026-07-08T12:00:00Z"
    assert context["feature_cutoff"] == "2026-07-08T11:59:00Z"
    assert context["decision_time"] == "2026-07-08T12:01:00Z"
    assert context["temporal_contract_valid"] is True
    assert context["feature_source_lineage"]["funding_rate"]["provider"] == "coinglass"
    assert len(context["source_lineage"]["coinglass"]["source_payload_sha256"]) == 64


@pytest.mark.parametrize("ttl_value", (None, -2, -1, 0))
def test_bridge_never_consumes_features_without_positive_ttl(
    ttl_value: int | None,
) -> None:
    r = FakeRedis()
    key = "v2:features:coinglass:BTCUSDT:1m"
    r.set(
        key,
        json.dumps(
            {
                "subscription_status": "READY",
                "actual_payload_present": True,
                "heartbeat_only": False,
                "available_at": "2026-07-08T12:00:00Z",
                "feature_cutoff": "2026-07-08T11:59:00Z",
                "features": {"coinglass_funding_rate": 0.0001},
            }
        ),
        ex=180,
    )
    if ttl_value is None:
        # Simulate a client that cannot prove expiry at all.
        r.ttl = None  # type: ignore[method-assign,assignment]
    else:
        r.ttls[key] = ttl_value

    context = build_provider_consumer_context(
        r,
        role="trainer",
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time="2026-07-08T12:01:00Z",
    )

    assert context["provider_features"] == {}
    assert context["provider_payloads"]["coinglass"]["ttl_contract_valid"] is False
    assert context["ttl_contract_violations"]


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


def test_bridge_does_not_infer_available_at_from_generated_at() -> None:
    r = FakeRedis()
    r.set(
        "v2:features:coinglass:BTCUSDT:1m",
        json.dumps(
            {
                "subscription_status": "READY",
                "actual_payload_present": True,
                "heartbeat_only": False,
                "generated_at": "2026-07-08T12:00:00Z",
                "feature_cutoff": "2026-07-08T11:59:00Z",
                "features": {"coinglass_funding_rate": 0.1},
            }
        ),
        ex=180,
    )

    context = build_provider_consumer_context(
        r,
        role="trainer",
        symbol="BTCUSDT",
        decision_time="2026-07-08T12:01:00Z",
    )

    assert context["provider_features"] == {}
    assert context["provider_payloads"]["coinglass"]["available_at"] is None
    assert any(
        "root:available_at_missing" in reason for reason in context["temporal_contract_violations"]
    )


def test_bridge_does_not_infer_feature_cutoff_from_event_or_availability() -> None:
    r = FakeRedis()
    r.set(
        "v2:features:coinglass:BTCUSDT:1m",
        json.dumps(
            {
                "subscription_status": "READY",
                "actual_payload_present": True,
                "heartbeat_only": False,
                "event_time": "2026-07-08T11:59:00Z",
                "available_at": "2026-07-08T12:00:00Z",
                "features": {"coinglass_funding_rate": 0.1},
            }
        ),
        ex=180,
    )

    context = build_provider_consumer_context(
        r,
        role="trainer",
        symbol="BTCUSDT",
        decision_time="2026-07-08T12:01:00Z",
    )

    assert context["provider_features"] == {}
    assert context["provider_payloads"]["coinglass"]["feature_cutoff"] is None
    assert any(
        "root:feature_cutoff_missing" in reason
        for reason in context["temporal_contract_violations"]
    )


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    (
        ("available_at", "2026-07-08T12:00:00", "available_at_not_strict_utc"),
        ("feature_cutoff", "not-a-time", "feature_cutoff_not_strict_utc"),
    ),
)
def test_bridge_rejects_naive_or_unparseable_source_clocks(
    field: str,
    value: str,
    reason: str,
) -> None:
    r = FakeRedis()
    payload = {
        "subscription_status": "READY",
        "actual_payload_present": True,
        "heartbeat_only": False,
        "available_at": "2026-07-08T12:00:00Z",
        "feature_cutoff": "2026-07-08T11:59:00Z",
        "features": {"coinglass_funding_rate": 0.1},
    }
    payload[field] = value
    r.set(
        "v2:features:coinglass:BTCUSDT:1m",
        json.dumps(payload),
        ex=180,
    )

    context = build_provider_consumer_context(
        r,
        role="trainer",
        symbol="BTCUSDT",
        decision_time="2026-07-08T12:01:00Z",
    )

    assert context["provider_features"] == {}
    assert any(reason in item for item in context["temporal_contract_violations"])


def test_bridge_rejects_naive_decision_time() -> None:
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
                "features": {"coinglass_funding_rate": 0.1},
            }
        ),
        ex=180,
    )

    context = build_provider_consumer_context(
        r,
        role="trainer",
        symbol="BTCUSDT",
        decision_time="2026-07-08T12:01:00",
    )

    assert context["decision_time"] is None
    assert context["provider_features"] == {}
    assert any(
        "decision_time_not_strict_utc" in reason
        for reason in context["temporal_contract_violations"]
    )


def test_bridge_rejects_inverted_source_clocks() -> None:
    r = FakeRedis()
    r.set(
        "v2:features:coinglass:BTCUSDT:1m",
        json.dumps(
            {
                "subscription_status": "READY",
                "actual_payload_present": True,
                "heartbeat_only": False,
                "available_at": "2026-07-08T12:00:00Z",
                "feature_cutoff": "2026-07-08T12:00:30Z",
                "features": {"coinglass_funding_rate": 0.1},
            }
        ),
        ex=180,
    )

    context = build_provider_consumer_context(
        r,
        role="trainer",
        symbol="BTCUSDT",
        decision_time="2026-07-08T12:01:00Z",
    )

    assert context["provider_features"] == {}
    assert any(
        "feature_cutoff_after_available_at" in reason
        for reason in context["temporal_contract_violations"]
    )


def test_bridge_rejects_future_nested_endpoint_clock_despite_causal_wrapper() -> None:
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
                "features": {"coinglass_funding_rate": 0.1},
                "endpoint_payloads": {
                    "funding": {
                        "actual_payload_present": True,
                        "available_at": "2026-07-08T12:02:00Z",
                        "feature_cutoff": "2026-07-08T11:59:00Z",
                        "features": {"coinglass_funding_rate": 0.1},
                    }
                },
            }
        ),
        ex=180,
    )

    context = build_provider_consumer_context(
        r,
        role="trainer",
        symbol="BTCUSDT",
        decision_time="2026-07-08T12:01:00Z",
    )

    assert context["provider_features"] == {}
    assert any(
        "endpoint_payloads.funding:available_at_after_decision_time" in reason
        for reason in context["temporal_contract_violations"]
    )


def test_bridge_rejects_nested_feature_row_missing_its_own_availability() -> None:
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
                "features": {"coinglass_funding_rate": 0.1},
                "endpoint_payloads": {
                    "funding": {
                        "actual_payload_present": True,
                        "feature_cutoff": "2026-07-08T11:59:00Z",
                        "features": {"coinglass_funding_rate": 0.1},
                    }
                },
            }
        ),
        ex=180,
    )

    context = build_provider_consumer_context(
        r,
        role="trainer",
        symbol="BTCUSDT",
        decision_time="2026-07-08T12:01:00Z",
    )

    assert context["provider_features"] == {}
    assert any(
        "endpoint_payloads.funding:available_at_missing" in reason
        for reason in context["temporal_contract_violations"]
    )


def test_bridge_uses_latest_literal_nested_clocks_for_conservative_envelope() -> None:
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
                "features": {"coinglass_funding_rate": 0.1},
                "endpoint_payloads": {
                    "funding": {
                        "actual_payload_present": True,
                        "available_at": "2026-07-08T12:00:15Z",
                        "feature_cutoff": "2026-07-08T11:59:30Z",
                        "features": {"coinglass_funding_rate": 0.1},
                    }
                },
            }
        ),
        ex=180,
    )

    context = build_provider_consumer_context(
        r,
        role="trainer",
        symbol="BTCUSDT",
        decision_time="2026-07-08T12:01:00Z",
    )

    assert context["provider_features"]["funding_rate"] == 0.1
    assert context["available_at"] == "2026-07-08T12:00:15Z"
    assert context["feature_cutoff"] == "2026-07-08T11:59:30Z"
    assert context["available_at"] <= context["decision_time"]
    assert context["feature_cutoff"] <= context["decision_time"]


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
