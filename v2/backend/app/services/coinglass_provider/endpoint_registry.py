"""CoinGlass endpoint registry and cadence contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class CoinGlassEndpointSpec:
    endpoint_id: str
    group: str
    path: str
    purpose: str
    priority: str
    cadence_seconds_top_symbols: int
    cadence_seconds_active_symbols: int
    cadence_seconds_full_universe: int
    rate_budget_per_minute: int
    ttl_seconds: int
    feature_outputs: tuple[str, ...]
    supports_batch: bool = False
    optional_if_plan_forbidden: bool = True
    # Params the v4 API requires beyond symbol (probed live 2026-07-08 against
    # the provisioned key; e.g. exchange=Binance plus an explicit interval).
    default_params: tuple[tuple[str, str], ...] = ()
    # "coin" strips USDT (BTC); "pair" keeps the full perp pair (BTCUSDT).
    symbol_format: str = "coin"
    # Historical endpoints must declare the exact aggregation interval used by
    # the provider.  The normalizer uses this to admit closed bars only and to
    # carry truthful temporal lineage into Redis.
    source_interval: str | None = None
    # Response scope is independent of supports_batch.  Only endpoints that
    # return all configured symbols from one request may opt into local fanout.
    response_scope: str = "per_symbol"
    # Historical rows fail closed once this many seconds have elapsed since
    # bar_close.  Standard-plan hourly bounds span the next hourly window plus
    # a small close-boundary overlap; they are absolute freshness deadlines.
    max_source_age_seconds: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


MAJOR_SYMBOLS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")


def coinglass_endpoint_registry() -> tuple[CoinGlassEndpointSpec, ...]:
    return (
        CoinGlassEndpointSpec(
            endpoint_id="market_snapshot",
            group="market_snapshot",
            path="/api/futures/pairs-markets",
            purpose="broad market context",
            priority="HIGH",
            cadence_seconds_top_symbols=60,
            cadence_seconds_active_symbols=120,
            cadence_seconds_full_universe=300,
            rate_budget_per_minute=20,
            ttl_seconds=300,
            feature_outputs=(
                "coinglass_price_usd",
                "coinglass_volume_24h_usd",
                "coinglass_price_change_24h_fraction",
                "coinglass_exchange_count",
                "coinglass_market_snapshot_volume_usd",
            ),
            supports_batch=True,
        ),
        CoinGlassEndpointSpec(
            endpoint_id="funding_rate",
            group="funding_rate",
            path="/api/futures/funding-rate/exchange-list",
            purpose="funding pressure and crowded perp positioning",
            priority="HIGH",
            cadence_seconds_top_symbols=60,
            cadence_seconds_active_symbols=120,
            cadence_seconds_full_universe=600,
            rate_budget_per_minute=30,
            ttl_seconds=180,
            feature_outputs=(
                "coinglass_funding_rate",
                "coinglass_next_funding_minutes",
            ),
            supports_batch=True,
            response_scope="all_symbols",
        ),
        CoinGlassEndpointSpec(
            endpoint_id="open_interest",
            group="open_interest",
            path="/api/futures/open-interest/exchange-list",
            purpose="open-interest expansion, flush, and regime context",
            priority="HIGH",
            cadence_seconds_top_symbols=60,
            cadence_seconds_active_symbols=120,
            cadence_seconds_full_universe=600,
            rate_budget_per_minute=40,
            ttl_seconds=180,
            feature_outputs=(
                "coinglass_open_interest_usd",
                "coinglass_open_interest_change_fraction_5m",
                "coinglass_open_interest_change_fraction_1h",
            ),
        ),
        CoinGlassEndpointSpec(
            endpoint_id="long_short_ratio",
            group="long_short_ratio",
            path="/api/futures/top-long-short-account-ratio/history",
            default_params=(("exchange", "Binance"), ("interval", "1h")),
            symbol_format="pair",
            source_interval="1h",
            max_source_age_seconds=3720,
            purpose="crowd positioning and squeeze risk",
            priority="HIGH",
            cadence_seconds_top_symbols=300,
            cadence_seconds_active_symbols=300,
            cadence_seconds_full_universe=300,
            rate_budget_per_minute=40,
            ttl_seconds=3720,
            feature_outputs=(
                "coinglass_long_ratio",
                "coinglass_short_ratio",
                "coinglass_long_short_extreme_score",
            ),
        ),
        CoinGlassEndpointSpec(
            endpoint_id="liquidation_orders",
            group="liquidation_orders",
            path="/api/futures/liquidation/aggregated-history",
            default_params=(("exchange_list", "Binance"), ("interval", "1h")),
            source_interval="1h",
            max_source_age_seconds=3660,
            purpose="Standard-plan hourly aggregate liquidation pressure",
            priority="CRITICAL_CONFLUENCE",
            cadence_seconds_top_symbols=300,
            cadence_seconds_active_symbols=300,
            cadence_seconds_full_universe=300,
            rate_budget_per_minute=50,
            ttl_seconds=3660,
            feature_outputs=(
                "coinglass_liquidation_buy_usd_1h",
                "coinglass_liquidation_sell_usd_1h",
                "coinglass_liquidation_total_usd_1h",
                "coinglass_liquidation_imbalance_usd",
            ),
        ),
        CoinGlassEndpointSpec(
            endpoint_id="liquidation_heatmap_or_levels",
            group="liquidation_heatmap_or_levels",
            path="/api/futures/liquidation/heatmap/model2",
            default_params=(("exchange", "Binance"), ("range", "12h")),
            symbol_format="pair",
            purpose="sweep targets and forced-liquidation zones",
            priority="HIGH",
            cadence_seconds_top_symbols=120,
            cadence_seconds_active_symbols=300,
            cadence_seconds_full_universe=900,
            rate_budget_per_minute=25,
            ttl_seconds=300,
            feature_outputs=(
                "coinglass_nearest_liq_zone_above_usd",
                "coinglass_nearest_liq_zone_below_usd",
                "coinglass_liq_zone_distance_usd",
            ),
        ),
        CoinGlassEndpointSpec(
            endpoint_id="trades",
            group="trades",
            path="/api/futures/v2/taker-buy-sell-volume/history",
            default_params=(("exchange", "Binance"), ("interval", "1h")),
            symbol_format="pair",
            source_interval="1h",
            max_source_age_seconds=3660,
            purpose="Standard-plan hourly tape confirmation",
            priority="HIGH",
            cadence_seconds_top_symbols=300,
            cadence_seconds_active_symbols=300,
            cadence_seconds_full_universe=300,
            rate_budget_per_minute=40,
            ttl_seconds=3660,
            feature_outputs=("coinglass_trade_imbalance_usd",),
        ),
        CoinGlassEndpointSpec(
            endpoint_id="orderbook_l2_l3",
            group="orderbook_l2_l3",
            path="/api/futures/orderbook/ask-bids-history",
            default_params=(("exchange", "Binance"), ("interval", "1h")),
            symbol_format="pair",
            source_interval="1h",
            max_source_age_seconds=3660,
            purpose="Standard-plan hourly orderbook depth context",
            priority="HIGH",
            cadence_seconds_top_symbols=300,
            cadence_seconds_active_symbols=300,
            cadence_seconds_full_universe=300,
            rate_budget_per_minute=40,
            ttl_seconds=3660,
            feature_outputs=(
                "coinglass_orderbook_depth_imbalance_usd",
            ),
        ),
        CoinGlassEndpointSpec(
            endpoint_id="exchange_metadata",
            group="exchange_metadata",
            path="/api/futures/supported-exchange-pairs",
            purpose="endpoint support and symbol mapping",
            priority="LOW",
            cadence_seconds_top_symbols=900,
            cadence_seconds_active_symbols=900,
            cadence_seconds_full_universe=900,
            rate_budget_per_minute=5,
            ttl_seconds=900,
            feature_outputs=(
                "coinglass_exchange_supported",
                "coinglass_symbol_supported",
            ),
            supports_batch=True,
        ),
    )


def registry_payload() -> dict[str, Any]:
    endpoints = [spec.as_dict() for spec in coinglass_endpoint_registry()]
    return {
        "schema_version": "coinglass_endpoint_registry_v1",
        "provider": "coinglass",
        "major_symbols": list(MAJOR_SYMBOLS),
        "normal_mode_max_per_minute": 210,
        "hard_limit_per_minute": 285,
        "manual_reserve_per_minute": 15,
        "health_reserve_per_minute": 5,
        "runtime_limit_note": (
            "Effective per-minute budget is resolved at runtime by "
            "CoinGlassRateLimiter from the API-KEY-MAX-LIMIT response header "
            "(ACCOUNT_HEADER_DISCOVERED beats these doc-derived numbers; "
            "discovered 80/min on 2026-07-08 -> 65/min usable after manual reserve)."
        ),
        "endpoint_count": len(endpoints),
        "endpoints": endpoints,
        "raw_key_exposed": False,
        "core_system_blocked": False,
    }
