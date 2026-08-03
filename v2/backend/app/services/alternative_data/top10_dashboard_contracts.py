"""Top-10 market and alternative-data dashboard contracts.

Contract-only. Does not call Binance, Arkham, or any exchange/provider
API. Does not write Redis. The contracts describe V2 source keys and
the expected missing/stale states that the website can render.
"""
from __future__ import annotations

from typing import Any

from v2.backend.app.services.alternative_data.provider_registry import (
    utc_iso,
)

SCHEMA_VERSION = "v2_top10_market_and_altdata_dashboard_contracts_v1"
GO_READY = "V2_TOP10_MARKET_AND_ALTDATA_DASHBOARD_CONTRACTS_READY"
GO_BLOCKED = "V2_TOP10_MARKET_AND_ALTDATA_DASHBOARD_CONTRACTS_BLOCKED"


def _market_panel(
    *,
    rank: int,
    panel_id: str,
    title: str,
    market_type: str,
    metric: str,
    required_metric_fields: list[str],
) -> dict[str, Any]:
    return {
        "rank": rank,
        "id": panel_id,
        "title": title,
        "category": "binance_market",
        "market_type": market_type,
        "enabled": True,
        "empty_until_runtime_source_available": False,
        "data_source_rule": (
            "Use Binance rolling-window stats when present; otherwise use "
            "locally computed 12h windows from V2 market data."
        ),
        "primary_v2_sources": [
            f"v2:market:binance:{market_type}:rolling_12h:{{symbol}}",
            "v2:market:prices:{symbol}",
            "v2:features:latest:{symbol}:1m",
        ],
        "required_fields": [
            "symbol",
            "rank",
            "generated_utc",
            "window_seconds",
            "source_freshness_seconds",
            "missing_source",
            "stale_flag",
            *required_metric_fields,
        ],
        "ranking_metric": metric,
        "missing_source_state": "MISSING_SOURCE",
        "credential_required": False,
        "raw_credentials_allowed": False,
    }


def build_top10_dashboard_contracts(
    *,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    # ``env`` is retained for API stability; the credential-presence
    # probe it fed was removed with the retired alt-data provider
    # panels (operator directive 2026-07-16).
    del env
    dashboards = [
        _market_panel(
            rank=1,
            panel_id="binance_spot_12h_volume_leaders",
            title="Binance Spot 12h Volume Leaders",
            market_type="spot",
            metric="quote_volume_12h",
            required_metric_fields=["quote_volume_12h", "base_volume_12h"],
        ),
        _market_panel(
            rank=2,
            panel_id="binance_futures_12h_volume_leaders",
            title="Binance Futures 12h Volume Leaders",
            market_type="futures",
            metric="quote_volume_12h",
            required_metric_fields=["quote_volume_12h", "contract_volume_12h"],
        ),
        _market_panel(
            rank=3,
            panel_id="binance_spot_12h_most_traded",
            title="Binance Spot 12h Most Traded",
            market_type="spot",
            metric="trade_count_12h",
            required_metric_fields=["trade_count_12h"],
        ),
        _market_panel(
            rank=4,
            panel_id="binance_futures_12h_most_traded",
            title="Binance Futures 12h Most Traded",
            market_type="futures",
            metric="trade_count_12h",
            required_metric_fields=["trade_count_12h"],
        ),
        _market_panel(
            rank=5,
            panel_id="binance_spot_12h_volatility_leaders",
            title="Binance Spot 12h Volatility Leaders",
            market_type="spot",
            metric="volatility_score_12h",
            required_metric_fields=["true_range_pct_12h", "volatility_score_12h"],
        ),
        _market_panel(
            rank=6,
            panel_id="binance_futures_12h_volatility_leaders",
            title="Binance Futures 12h Volatility Leaders",
            market_type="futures",
            metric="volatility_score_12h",
            required_metric_fields=["true_range_pct_12h", "volatility_score_12h"],
        ),
        {
            "rank": 7,
            "id": "liquidation_tape_top_symbols",
            "title": "Liquidation Tape Top Symbols",
            "category": "liquidation_wss_existing",
            "enabled": True,
            "data_source_rule": "Use V2 liquidation WSS aggregates only; never synthesize liquidation events.",
            "primary_v2_sources": [
                "v2:market:liquidations:heartbeat",
                "v2:market:liquidations:latest:{symbol}",
                "v2:market:liquidations:aggregate:{symbol}",
            ],
            "required_fields": [
                "symbol",
                "rank",
                "latest_notional",
                "latest_side",
                "notional_1h",
                "notional_24h",
                "direction_bias_1h",
                "missing_source",
                "stale_flag",
                "generated_utc",
            ],
            "missing_source_state": "MISSING_SOURCE",
            "no_synthetic_liquidation_events": True,
            "credential_required": False,
            "raw_credentials_allowed": False,
        },
        {
            "rank": 8,
            "id": "funding_oi_movers",
            "title": "Funding/OI Movers",
            "category": "coinank_existing",
            "enabled": True,
            "data_source_rule": "Use V2-native CoinAnk/funding/open-interest payloads only.",
            "primary_v2_sources": [
                "v2:market:funding:{symbol}",
                "v2:market:open_interest:{symbol}",
                "v2/frontend/public/operator_runtime/coinank_market_intelligence/latest/coinank_market_intelligence_status.json",
            ],
            "required_fields": [
                "symbol",
                "rank",
                "funding_rate",
                "open_interest",
                "open_interest_change_12h",
                "funding_change_12h",
                "missing_source",
                "stale_flag",
                "generated_utc",
            ],
            "missing_source_state": "MISSING_SOURCE",
            "credential_required": False,
            "raw_credentials_allowed": False,
        },
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": utc_iso(),
        "go_no_go": GO_READY,
        "dashboard_count": len(dashboards),
        "dashboards": dashboards,
        "provider_clients_implemented": False,
        "provider_network_calls_attempted": False,
        "alternative_data_dashboards_enabled": False,
        "raw_values_exposed": False,
        "paid_tier_enabled": False,
        "checkpoint_compatibility_claimed": False,
        "policy_architecture_parity_claimed": False,
        "paper_shadow_only": True,
        "may_not_override_strict_paper_fill_gate": True,
        "writes_old_redis": False,
        "exchange_mutation": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }


def build_public_payload(*, env: dict[str, str] | None = None) -> dict[str, Any]:
    contracts = build_top10_dashboard_contracts(env=env)
    return {
        "schema_version": "v2_top10_market_and_altdata_dashboard_payload_v1",
        "generated_utc": contracts["generated_utc"],
        "go_no_go": contracts["go_no_go"],
        "dashboard_count": contracts["dashboard_count"],
        "dashboard_ids": [row["id"] for row in contracts["dashboards"]],
        "dashboards": contracts["dashboards"],
        "provider_clients_implemented": False,
        "provider_network_calls_attempted": False,
        "alternative_data_dashboards_enabled": False,
        "raw_values_exposed": False,
        "paid_tier_enabled": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "writes_old_redis": False,
        "exchange_mutation": False,
    }
