"""Provider Redis key and endpoint-to-feature contracts."""

from __future__ import annotations

from typing import Any

from app.services.coinglass_provider.endpoint_registry import (
    coinglass_endpoint_registry,
)
from app.services.smart_money_wallets.endpoint_registry import (
    moralis_endpoint_registry,
)

COINGLASS_REDIS_KEY_CONTRACT: dict[str, str] = {
    "health": "v2:provider:coinglass:health",
    "usage": "v2:provider:coinglass:usage",
    "endpoint_status": "v2:provider:coinglass:endpoint_status",
    "funding": "v2:coinglass:funding:{symbol}",
    "open_interest": "v2:coinglass:open_interest:{symbol}",
    "long_short": "v2:coinglass:long_short:{symbol}",
    "liquidations": "v2:coinglass:liquidations:{symbol}",
    "liquidation_levels": "v2:coinglass:liquidation_levels:{symbol}",
    "market_snapshot": "v2:coinglass:market_snapshot:{symbol}",
    "trades": "v2:coinglass:trades:{symbol}",
    "orderbook": "v2:coinglass:orderbook:{symbol}",
    "features": "v2:features:coinglass:{symbol}:{timeframe}",
}

MORALIS_REDIS_KEY_CONTRACT: dict[str, str] = {
    "health": "v2:provider:moralis:health",
    "usage": "v2:provider:moralis:usage",
    "endpoint_status": "v2:provider:moralis:endpoint_status",
    "wallet": "v2:moralis:wallet:{chain}:{address}",
    "wallet_history": "v2:moralis:wallet_history:{chain}:{address}",
    "token_transfers": "v2:moralis:token_transfers:{chain}:{token}",
    "token_holders": "v2:moralis:token_holders:{chain}:{token}",
    "swaps": "v2:moralis:swaps:{chain}:{token}",
    "smart_money_signals": "v2:smart_money:signals:{symbol}",
    "features": "v2:features:moralis:{symbol}:{timeframe}",
    "symbol_score": "v2:provider:moralis:symbol_score:{symbol}",
}

CONSUMER_ROLES: tuple[str, ...] = (
    "trainer",
    "risk",
    "orchestrator",
    "allocator",
    "paper",
    "live_dry_run",
)

COINGLASS_CANONICAL_FEATURE_MAP: dict[str, str] = {
    "coinglass_funding_rate": "funding_rate",
    "coinglass_open_interest_usd": "open_interest",
    "coinglass_open_interest_delta_usd_5m": "oi_change_pct",
    "coinglass_long_ratio": "long_account_ratio",
    "coinglass_short_ratio": "short_account_ratio",
    "coinglass_long_short_extreme_score": "long_short_extreme_score",
    # CoinGlass Standard exposes the admitted liquidation history at 1h.
    # Never alias these observations to the legacy ``*_1m`` tensor names:
    # doing so changes the measurement window by 60x while keeping the old
    # label and makes provider collisions impossible to reason about.
    "coinglass_liquidation_buy_usd_1h": "liquidation_buy_usd_1h",
    "coinglass_liquidation_sell_usd_1h": "liquidation_sell_usd_1h",
    "coinglass_liquidation_total_usd_1h": "liquidation_total_usd_1h",
    "coinglass_liquidation_imbalance_usd": "liquidation_imbalance_usd",
    "coinglass_liquidation_cascade_score": "liquidation_cascade_risk",
    "coinglass_nearest_liq_zone_above_usd": "nearest_liquidation_level_above",
    "coinglass_nearest_liq_zone_below_usd": "nearest_liquidation_level_below",
    "coinglass_liq_zone_distance_usd": "liquidation_level_distance_usd",
    "coinglass_trade_imbalance_usd": "trade_imbalance",
    "coinglass_orderbook_depth_imbalance_usd": "orderbook_depth_imbalance",
}

MORALIS_CANONICAL_FEATURE_MAP: dict[str, str] = {
    "moralis_whale_net_flow_usd": "smart_money_whale_net_flow_usd",
    "moralis_whale_buy_usd": "smart_money_whale_buy_usd",
    "moralis_whale_sell_usd": "smart_money_whale_sell_usd",
    "moralis_smart_wallet_accumulation_score": "smart_wallet_accumulation_score",
    "moralis_smart_wallet_distribution_score": "smart_wallet_distribution_score",
    "moralis_exchange_inflow_usd": "smart_money_exchange_inflow_usd",
    "moralis_exchange_outflow_usd": "smart_money_exchange_outflow_usd",
    "moralis_net_exchange_flow_usd": "smart_money_net_exchange_flow_usd",
    "moralis_dex_buy_pressure_usd": "dex_buy_pressure_usd",
    "moralis_dex_sell_pressure_usd": "dex_sell_pressure_usd",
    "moralis_dex_flow_imbalance_usd": "dex_flow_imbalance_usd",
    "moralis_top_holder_concentration": "token_holder_top_concentration",
    "moralis_holder_count": "token_holder_count",
    "moralis_holder_delta": "token_holder_delta",
    "moralis_onchain_risk_score": "onchain_risk_score",
}


def provider_redis_key_contract() -> dict[str, Any]:
    return {
        "schema_version": "provider_redis_key_contract_v1",
        "coinglass": dict(COINGLASS_REDIS_KEY_CONTRACT),
        "moralis": dict(MORALIS_REDIS_KEY_CONTRACT),
        "ttl_required_for_payload_keys": True,
        "health_key_is_not_sufficient_for_green": True,
        "heartbeat_only_green_allowed": False,
        "raw_api_key_exposure_allowed": False,
    }


def endpoint_to_feature_mapping() -> dict[str, Any]:
    coinglass = {
        spec.endpoint_id: {
            "provider": "coinglass",
            "group": spec.group,
            "path": spec.path,
            "cadence_seconds": {
                "top_symbols": spec.cadence_seconds_top_symbols,
                "active_symbols": spec.cadence_seconds_active_symbols,
                "full_universe": spec.cadence_seconds_full_universe,
            },
            "request_budget_per_minute": spec.rate_budget_per_minute,
            "ttl_seconds": spec.ttl_seconds,
            "feature_outputs": list(spec.feature_outputs),
            "canonical_outputs": [
                COINGLASS_CANONICAL_FEATURE_MAP.get(name, name) for name in spec.feature_outputs
            ],
            "optional_if_forbidden": bool(spec.optional_if_plan_forbidden),
        }
        for spec in coinglass_endpoint_registry()
    }
    moralis = {
        spec.endpoint_id: {
            "provider": "moralis",
            "group": spec.group,
            "path_template": spec.path_template,
            "cadence_seconds": {
                "tier0_wallet_token_stream": spec.cadence_seconds_tier0,
                "tier1_wallet_token_stream": spec.cadence_seconds_tier1,
                "full_watchlist": spec.cadence_seconds_full_watchlist,
            },
            "compute_unit_cost": spec.cu_cost,
            "ttl_seconds": spec.ttl_seconds,
            "feature_outputs": list(spec.feature_outputs),
            "canonical_outputs": [
                MORALIS_CANONICAL_FEATURE_MAP.get(name, name) for name in spec.feature_outputs
            ],
            "requires_wallet": bool(spec.requires_wallet),
            "requires_token": bool(spec.requires_token),
            "stream_based": bool(spec.stream_based),
        }
        for spec in moralis_endpoint_registry()
    }
    return {
        "schema_version": "endpoint_to_feature_mapping_v1",
        "coinglass": coinglass,
        "moralis": moralis,
        "optional_provider_failures_core_blocking": False,
        "moralis_every_symbol_every_minute_allowed": False,
    }
