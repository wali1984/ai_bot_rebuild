"""Moralis payload to smart-money feature mapping."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.services.smart_money_wallets.endpoint_registry import MoralisEndpointSpec


def normalize_moralis_payload(
    *,
    spec: MoralisEndpointSpec,
    symbol: str | None,
    chain: str,
    wallet: str | None,
    token: str | None,
    payload: Any,
) -> dict[str, Any]:
    rows = _rows(payload)
    features: dict[str, float] = {}
    if spec.group in {"wallet_balances", "wallet_token_balances_price"}:
        usd_value = sum(_float(row.get("usd_value")) or 0.0 for row in rows)
        if usd_value > 0:
            features["moralis_whale_net_flow_usd"] = usd_value
            features["moralis_smart_wallet_accumulation_score"] = min(1.0, usd_value / 1_000_000.0)
            features["moralis_smart_wallet_distribution_score"] = 1.0 - min(
                1.0, usd_value / 1_000_000.0
            )
    elif spec.group == "wallet_networth":
        networth = _float(
            _first_mapping(payload).get("total_networth_usd")
            or _first_mapping(payload).get("networth_usd")
        )
        if networth is not None:
            features["moralis_whale_net_flow_usd"] = networth
            features["moralis_smart_wallet_accumulation_score"] = min(1.0, networth / 1_000_000.0)
            features["moralis_smart_wallet_distribution_score"] = 1.0 - min(
                1.0, networth / 1_000_000.0
            )
    elif spec.group in {
        "wallet_history",
        "wallet_transactions",
        "wallet_address_transfers",
        "token_transfers",
        "token_address_transfers",
    }:
        in_usd, out_usd = _flow_usd(rows)
        if in_usd or out_usd:
            features["moralis_exchange_inflow_usd"] = in_usd
            features["moralis_exchange_outflow_usd"] = out_usd
            features["moralis_net_exchange_flow_usd"] = out_usd - in_usd
    elif spec.group == "token_holders":
        holder_count = len(rows)
        if holder_count:
            # Holder count features
            features["moralis_holder_count"] = float(holder_count)
            features["moralis_holder_delta"] = float(holder_count)
            features["moralis_top_holder_concentration"] = _holder_concentration(rows)
    elif spec.group in {"swaps", "wallet_swaps", "token_swaps"}:
        buy_usd, sell_usd = _swap_usd(rows)
        if buy_usd or sell_usd:
            # Whale buy/sell (from swap data)
            features["moralis_whale_buy_usd"] = buy_usd
            features["moralis_whale_sell_usd"] = sell_usd
            features["moralis_whale_net_flow_usd"] = buy_usd - sell_usd
            # DEX pressure metrics
            features["moralis_dex_buy_pressure_usd"] = buy_usd
            features["moralis_dex_sell_pressure_usd"] = sell_usd
            features["moralis_dex_flow_imbalance_usd"] = buy_usd - sell_usd
    elif spec.group in {"price_ohlc", "token_price", "multiple_token_prices"}:
        price = _float(
            _first_mapping(payload).get("usdPrice") or _first_mapping(payload).get("usd_price")
        )
        if price is not None:
            features["moralis_onchain_risk_score"] = 0.0
    elif spec.group == "token_metadata":
        meta = _first_mapping(payload)
        if meta:
            features["moralis_onchain_risk_score"] = 0.0
    elif spec.group == "streams":
        features.update(_stream_features(payload))
    actual = bool(features)
    return {
        "schema_version": "moralis_normalized_payload_v1",
        "provider": "moralis",
        "endpoint_id": spec.endpoint_id,
        "feature_family": spec.group,
        "symbol": symbol,
        "chain": chain,
        "wallet": wallet,
        "token": token,
        "event_time": _event_time(rows),
        "generated_at": _now(),
        "features": features,
        "actual_payload_present": actual,
        "heartbeat_only": not actual,
        "core_system_blocked": False,
        "raw_key_exposed": False,
    }


def _rows(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, Mapping):
        result = payload.get("result")
        if isinstance(result, list):
            return [row for row in result if isinstance(row, Mapping)]
        if isinstance(result, Mapping):
            return [result]
        return [payload]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    return []


def _first_mapping(payload: Any) -> Mapping[str, Any]:
    if isinstance(payload, Mapping):
        return payload
    rows = _rows(payload)
    return rows[0] if rows else {}


def _flow_usd(rows: list[Mapping[str, Any]]) -> tuple[float, float]:
    in_usd = 0.0
    out_usd = 0.0
    for row in rows:
        value = (
            _float(row.get("value_usd") or row.get("usd_value") or row.get("value_decimal")) or 0.0
        )
        direction = str(row.get("direction") or row.get("category") or "").lower()
        if "in" in direction:
            in_usd += value
        elif "out" in direction:
            out_usd += value
        else:
            out_usd += value
    return in_usd, out_usd


def _swap_usd(rows: list[Mapping[str, Any]]) -> tuple[float, float]:
    buy = 0.0
    sell = 0.0
    for row in rows:
        side = str(row.get("side") or row.get("transaction_type") or "").lower()
        value = _float(row.get("total_value_usd") or row.get("usd_value")) or 0.0
        if side == "buy":
            buy += value
        elif side == "sell":
            sell += value
    return buy, sell


def _stream_features(payload: Any) -> dict[str, float]:
    if not isinstance(payload, Mapping):
        return {}
    transfers = payload.get("erc20Transfers")
    transfers_count = len(transfers) if isinstance(transfers, list) else 0
    txs = payload.get("txs")
    tx_count = len(txs) if isinstance(txs, list) else 0
    if not transfers_count and not tx_count:
        return {}
    return {
        "moralis_whale_buy_usd": 0.0,
        "moralis_whale_sell_usd": 0.0,
        "moralis_whale_net_flow_usd": float(transfers_count + tx_count),
    }


def _event_time(rows: list[Mapping[str, Any]]) -> str | None:
    if not rows:
        return None
    contributing_clocks: list[datetime] = []
    for row in rows:
        value = row.get("block_timestamp") or row.get("timestamp")
        parsed = _strict_source_time(value)
        # The feature extractors aggregate across the full row set. If any row
        # lacks a valid source clock, no exact latest-contributing cutoff can be
        # asserted, so the entire source feature is rejected downstream.
        if parsed is None:
            return None
        contributing_clocks.append(parsed)
    latest = max(contributing_clocks)
    return latest.isoformat().replace("+00:00", "Z")


def _strict_source_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _holder_concentration(rows: list[Mapping[str, Any]]) -> float:
    """Calculate concentration of top holders (Herfindahl index)."""
    if not rows or len(rows) < 2:
        return 0.0
    total = sum(
        _float(row.get("balance") or row.get("balance_with_decimals")) or 0.0 for row in rows
    )
    if total <= 0:
        return 0.0
    concentrations = []
    for row in rows[:10]:  # top 10 holders
        holder_balance = _float(row.get("balance") or row.get("balance_with_decimals")) or 0.0
        if holder_balance > 0:
            concentrations.append((holder_balance / total) ** 2)
    herfindahl = sum(concentrations)
    return min(1.0, herfindahl)


def _float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
