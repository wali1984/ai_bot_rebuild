from __future__ import annotations

from v2.backend.app.services.provider_features.contracts import (
    COINGLASS_CANONICAL_FEATURE_MAP,
    endpoint_to_feature_mapping,
)


def test_standard_liquidation_history_keeps_truthful_one_hour_names() -> None:
    mapping = endpoint_to_feature_mapping()["coinglass"]["liquidation_orders"]

    assert mapping["feature_outputs"] == [
        "coinglass_liquidation_buy_usd_1h",
        "coinglass_liquidation_sell_usd_1h",
        "coinglass_liquidation_total_usd_1h",
        "coinglass_liquidation_imbalance_usd",
    ]
    assert mapping["canonical_outputs"] == [
        "liquidation_buy_usd_1h",
        "liquidation_sell_usd_1h",
        "liquidation_total_usd_1h",
        "liquidation_imbalance_usd",
    ]


def test_no_hourly_coinglass_feature_is_aliased_to_one_minute() -> None:
    for source_name, canonical_name in COINGLASS_CANONICAL_FEATURE_MAP.items():
        if source_name.endswith("_1h"):
            assert not canonical_name.endswith("_1m")

    assert "coinglass_liquidation_buy_usd_1m" not in (
        COINGLASS_CANONICAL_FEATURE_MAP
    )
    assert "coinglass_liquidation_sell_usd_1m" not in (
        COINGLASS_CANONICAL_FEATURE_MAP
    )
