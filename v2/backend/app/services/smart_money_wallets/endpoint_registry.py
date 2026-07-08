"""Moralis smart-money endpoint registry and CU cadence contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class MoralisEndpointSpec:
    endpoint_id: str
    group: str
    path_template: str
    purpose: str
    priority: str
    cu_cost: int
    cadence_seconds_tier0: int
    cadence_seconds_tier1: int
    cadence_seconds_full_watchlist: int
    ttl_seconds: int
    feature_outputs: tuple[str, ...]
    requires_wallet: bool = False
    requires_token: bool = False
    stream_based: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def moralis_endpoint_registry() -> tuple[MoralisEndpointSpec, ...]:
    return (
        MoralisEndpointSpec(
            endpoint_id="wallet_token_balances_price",
            group="wallet_token_balances_price",
            path_template="/wallets/{wallet}/tokens?chain={chain}",
            purpose="track known wallet holdings and token balances with price",
            priority="MEDIUM",
            cu_cost=100,
            cadence_seconds_tier0=1800,
            cadence_seconds_tier1=7200,
            cadence_seconds_full_watchlist=21600,
            ttl_seconds=21600,
            feature_outputs=(
                "moralis_smart_wallet_accumulation_score",
                "moralis_whale_net_flow_usd",
            ),
            requires_wallet=True,
        ),
        MoralisEndpointSpec(
            endpoint_id="wallet_history",
            group="wallet_history",
            path_template="/wallets/{wallet}/history?chain={chain}",
            purpose="wallet activity and realized flow",
            priority="MEDIUM_HIGH",
            cu_cost=150,
            cadence_seconds_tier0=900,
            cadence_seconds_tier1=3600,
            cadence_seconds_full_watchlist=21600,
            ttl_seconds=21600,
            feature_outputs=(
                "moralis_exchange_inflow_usd",
                "moralis_exchange_outflow_usd",
                "moralis_net_exchange_flow_usd",
            ),
            requires_wallet=True,
        ),
        MoralisEndpointSpec(
            endpoint_id="wallet_transactions",
            group="wallet_transactions",
            path_template="/wallets/{wallet}/transactions?chain={chain}",
            purpose="wallet transaction activity and realized flow proxy",
            priority="MEDIUM_HIGH",
            cu_cost=100,
            cadence_seconds_tier0=900,
            cadence_seconds_tier1=3600,
            cadence_seconds_full_watchlist=21600,
            ttl_seconds=21600,
            feature_outputs=(
                "moralis_exchange_inflow_usd",
                "moralis_exchange_outflow_usd",
                "moralis_net_exchange_flow_usd",
            ),
            requires_wallet=True,
        ),
        MoralisEndpointSpec(
            endpoint_id="wallet_networth",
            group="wallet_networth",
            path_template="/wallets/{wallet}/net-worth?chain={chain}",
            purpose="wallet size and whale-score context",
            priority="MEDIUM",
            cu_cost=100,
            cadence_seconds_tier0=1800,
            cadence_seconds_tier1=7200,
            cadence_seconds_full_watchlist=21600,
            ttl_seconds=21600,
            feature_outputs=(
                "moralis_whale_net_flow_usd",
                "moralis_smart_wallet_accumulation_score",
            ),
            requires_wallet=True,
        ),
        MoralisEndpointSpec(
            endpoint_id="wallet_address_transfers",
            group="wallet_address_transfers",
            path_template="/wallets/{wallet}/history?chain={chain}",
            purpose="wallet address transfer flow",
            priority="MEDIUM_HIGH",
            cu_cost=150,
            cadence_seconds_tier0=900,
            cadence_seconds_tier1=3600,
            cadence_seconds_full_watchlist=21600,
            ttl_seconds=21600,
            feature_outputs=(
                "moralis_exchange_inflow_usd",
                "moralis_exchange_outflow_usd",
                "moralis_net_exchange_flow_usd",
            ),
            requires_wallet=True,
        ),
        MoralisEndpointSpec(
            endpoint_id="token_transfers",
            group="token_transfers",
            path_template="/erc20/{token}/transfers?chain={chain}",
            purpose="exchange inflow/outflow and whale token flows",
            priority="MEDIUM_HIGH",
            cu_cost=50,
            cadence_seconds_tier0=600,
            cadence_seconds_tier1=900,
            cadence_seconds_full_watchlist=21600,
            ttl_seconds=3600,
            feature_outputs=(
                "moralis_exchange_inflow_usd",
                "moralis_exchange_outflow_usd",
                "moralis_net_exchange_flow_usd",
            ),
            requires_token=True,
        ),
        MoralisEndpointSpec(
            endpoint_id="token_address_transfers",
            group="token_address_transfers",
            path_template="/erc20/{token}/transfers?chain={chain}",
            purpose="large recent token transfer participants",
            priority="MEDIUM_HIGH",
            cu_cost=50,
            cadence_seconds_tier0=600,
            cadence_seconds_tier1=900,
            cadence_seconds_full_watchlist=21600,
            ttl_seconds=3600,
            feature_outputs=(
                "moralis_exchange_inflow_usd",
                "moralis_exchange_outflow_usd",
                "moralis_net_exchange_flow_usd",
            ),
            requires_token=True,
        ),
        MoralisEndpointSpec(
            endpoint_id="token_holders",
            group="token_holders",
            path_template="/erc20/{token}/owners?chain={chain}",
            purpose="holder concentration and accumulation/distribution",
            priority="LOW_MEDIUM",
            cu_cost=50,
            cadence_seconds_tier0=21600,
            cadence_seconds_tier1=21600,
            cadence_seconds_full_watchlist=86400,
            ttl_seconds=86400,
            feature_outputs=(
                "moralis_holder_concentration_change",
                "moralis_token_holder_delta",
            ),
            requires_token=True,
        ),
        MoralisEndpointSpec(
            endpoint_id="wallet_swaps",
            group="wallet_swaps",
            path_template="/wallets/{wallet}/swaps?chain={chain}",
            purpose="DEX buy/sell pressure",
            priority="MEDIUM",
            cu_cost=50,
            cadence_seconds_tier0=600,
            cadence_seconds_tier1=900,
            cadence_seconds_full_watchlist=21600,
            ttl_seconds=3600,
            feature_outputs=(
                "moralis_dex_buy_pressure_usd",
                "moralis_dex_sell_pressure_usd",
                "moralis_dex_flow_imbalance_usd",
            ),
            requires_wallet=True,
        ),
        MoralisEndpointSpec(
            endpoint_id="token_swaps",
            group="token_swaps",
            path_template="/erc20/{token}/swaps?chain={chain}",
            purpose="token-level DEX buy/sell pressure",
            priority="MEDIUM",
            cu_cost=50,
            cadence_seconds_tier0=600,
            cadence_seconds_tier1=900,
            cadence_seconds_full_watchlist=21600,
            ttl_seconds=3600,
            feature_outputs=(
                "moralis_dex_buy_pressure_usd",
                "moralis_dex_sell_pressure_usd",
                "moralis_dex_flow_imbalance_usd",
            ),
            requires_token=True,
        ),
        MoralisEndpointSpec(
            endpoint_id="token_metadata",
            group="token_metadata",
            path_template="/erc20/metadata?chain={chain}&addresses={token}",
            purpose="metadata validation for symbol-to-contract map",
            priority="LOW_MEDIUM",
            cu_cost=25,
            cadence_seconds_tier0=21600,
            cadence_seconds_tier1=21600,
            cadence_seconds_full_watchlist=86400,
            ttl_seconds=86400,
            feature_outputs=(
                "moralis_contract_risk_penalty",
                "moralis_onchain_risk_score",
            ),
            requires_token=True,
        ),
        MoralisEndpointSpec(
            endpoint_id="token_price",
            group="token_price",
            path_template="/erc20/{token}/price?chain={chain}",
            purpose="onchain price confirmation only",
            priority="LOW",
            cu_cost=50,
            cadence_seconds_tier0=900,
            cadence_seconds_tier1=900,
            cadence_seconds_full_watchlist=21600,
            ttl_seconds=900,
            feature_outputs=("moralis_onchain_risk_score",),
            requires_token=True,
        ),
        MoralisEndpointSpec(
            endpoint_id="multiple_token_prices",
            group="multiple_token_prices",
            path_template="/erc20/prices?chain={chain}&tokens={token}",
            purpose="batched token price confirmation where supported",
            priority="LOW",
            cu_cost=50,
            cadence_seconds_tier0=900,
            cadence_seconds_tier1=900,
            cadence_seconds_full_watchlist=21600,
            ttl_seconds=900,
            feature_outputs=("moralis_onchain_risk_score",),
            requires_token=True,
        ),
        MoralisEndpointSpec(
            endpoint_id="streams",
            group="streams",
            path_template="webhook",
            purpose="push-based wallet/address/token events",
            priority="HIGH_ONCE_CONFIGURED",
            cu_cost=10,
            cadence_seconds_tier0=0,
            cadence_seconds_tier1=0,
            cadence_seconds_full_watchlist=0,
            ttl_seconds=3600,
            feature_outputs=(
                "moralis_whale_buy_usd",
                "moralis_whale_sell_usd",
                "moralis_whale_net_flow_usd",
            ),
            stream_based=True,
        ),
    )


def registry_payload() -> dict[str, Any]:
    endpoints = [spec.as_dict() for spec in moralis_endpoint_registry()]
    return {
        "schema_version": "moralis_endpoint_registry_v1",
        "provider": "moralis",
        "public_plan": "starter",
        "public_rps": 40,
        "public_monthly_compute_units": 2_000_000,
        "daily_compute_unit_budget": 55_000,
        "daily_compute_unit_reserve": 10_000,
        "normal_max_rps": 5,
        "catchup_max_rps": 10,
        "hard_max_rps": 30,
        "endpoint_count": len(endpoints),
        "endpoints": endpoints,
        "wallet_token_stream_cadence_contract": {
            "t0_wallet_history_transfers_swaps_seconds": 900,
            "t0_wallet_balances_networth_seconds": 1800,
            "t1_wallet_history_transfers_swaps_seconds": 3600,
            "t1_wallet_balances_networth_seconds": 7200,
            "token_transfers_swaps_active_symbols_seconds": "600-1800",
            "token_holders_seconds": "21600-86400",
            "full_universe": "rotating_only",
        },
        "raw_key_exposed": False,
        "core_system_blocked": False,
    }
