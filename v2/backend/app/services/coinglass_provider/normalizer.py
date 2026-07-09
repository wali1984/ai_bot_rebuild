"""CoinGlass payload to feature mapping."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from app.services.coinglass_provider.endpoint_registry import CoinGlassEndpointSpec


def normalize_coinglass_payload(
    *,
    spec: CoinGlassEndpointSpec,
    symbol: str,
    payload: Any,
) -> dict[str, Any]:
    data = _data(payload)
    row = _last_row(data)
    features: dict[str, float] = {}
    if spec.group == "funding_rate":
        # v4 exchange-list returns ALL coins; each row is
        # {symbol, stablecoin_margin_list: [{exchange, funding_rate,
        #  next_funding_time}, ...], token_margin_list: [...]}.
        row = _funding_row_for_symbol(data, symbol) or row
        rate = _first_float(row, "funding_rate", "fundingRate", "close")
        if rate is not None:
            features["coinglass_funding_rate"] = rate
            features["coinglass_funding_rate_zscore"] = 0.0
        next_funding = _first_float(row, "next_funding_time", "nextFundingTime")
        if next_funding is not None:
            now_ms = datetime.now(timezone.utc).timestamp() * 1000.0
            features["coinglass_next_funding_minutes"] = max(0.0, (next_funding - now_ms) / 60000.0)
    elif spec.group == "open_interest":
        oi = _first_float(
            row,
            "open_interest_usd",
            "openInterestUsd",
            "open_interest",
            "close",
        )
        if oi is not None:
            features["coinglass_open_interest_usd"] = oi
        features.update(_optional_deltas(row))
    elif spec.group == "long_short_ratio":
        long_pct = _first_float(row, "top_account_long_percent", "longAccount", "long_ratio")
        short_pct = _first_float(row, "top_account_short_percent", "shortAccount", "short_ratio")
        ratio = _first_float(row, "top_account_long_short_ratio", "longShortRatio", "long_short_ratio")
        if long_pct is not None:
            features["coinglass_long_ratio"] = long_pct
        if short_pct is not None:
            features["coinglass_short_ratio"] = short_pct
        if ratio is not None:
            features["coinglass_long_short_extreme_score"] = min(1.0, abs(ratio - 1.0) / 2.0)
    elif spec.group == "liquidation_orders":
        buy = _first_float(row, "aggregated_short_liquidation_usd", "shortLiquidationUsd", "buy_usd")
        sell = _first_float(row, "aggregated_long_liquidation_usd", "longLiquidationUsd", "sell_usd")
        if buy is not None:
            features["coinglass_liquidation_buy_usd_1m"] = buy
        if sell is not None:
            features["coinglass_liquidation_sell_usd_1m"] = sell
        if buy is not None or sell is not None:
            features["coinglass_liquidation_imbalance_usd"] = float(buy or 0.0) - float(sell or 0.0)
            features["coinglass_liquidation_cascade_score"] = min(1.0, (abs(float(buy or 0.0) - float(sell or 0.0)) / max(1.0, float(buy or 0.0) + float(sell or 0.0))))
    elif spec.group == "liquidation_heatmap_or_levels":
        above = _first_float(row, "nearest_above_usd", "liquidation_level_above_usd")
        below = _first_float(row, "nearest_below_usd", "liquidation_level_below_usd")
        if above is not None:
            features["coinglass_nearest_liq_zone_above_usd"] = above
        if below is not None:
            features["coinglass_nearest_liq_zone_below_usd"] = below
        if above is not None and below is not None:
            features["coinglass_liq_zone_distance_usd"] = abs(above - below)
    elif spec.group == "market_snapshot":
        # v4 pairs-markets returns one row per exchange instrument; pick the
        # Binance perp row for price/24h-change and aggregate volume/OI
        # across venues so the snapshot reflects the whole market.
        rows = data if isinstance(data, list) else []
        exch_rows = [r for r in rows if isinstance(r, Mapping)]
        binance = [
            r for r in exch_rows
            if str(r.get("exchange_name")).lower() == "binance"
        ]
        primary = binance[0] if binance else row
        price = _first_float(primary, "current_price", "price_usd", "price")
        if price is not None:
            features["coinglass_price_usd"] = price
        change = _first_float(primary, "price_change_percent_24h", "price_change_24h_pct")
        if change is not None:
            features["coinglass_price_change_24h_pct"] = change
        volumes = [
            v for v in (
                _first_float(r, "volume_usd", "volume_24h_usd", "turnover_usd")
                for r in exch_rows
            )
            if v is not None
        ]
        if volumes:
            features["coinglass_volume_24h_usd"] = float(sum(volumes))
            features["coinglass_market_snapshot_volume_usd"] = float(sum(volumes))
        if exch_rows:
            features["coinglass_exchange_count"] = float(
                len({str(r.get("exchange_name")) for r in exch_rows})
            )
    elif spec.group == "trades":
        buy = _first_float(
            row, "taker_buy_volume_usd", "aggressive_buy_usd", "buy_usd"
        )
        sell = _first_float(
            row, "taker_sell_volume_usd", "aggressive_sell_usd", "sell_usd"
        )
        if buy is not None or sell is not None:
            features["coinglass_trade_imbalance_usd"] = float(buy or 0.0) - float(sell or 0.0)
    elif spec.group == "orderbook_l2_l3":
        bid = _first_float(row, "bid_usd", "bids_usd", "bidVolume")
        ask = _first_float(row, "ask_usd", "asks_usd", "askVolume")
        if bid is not None or ask is not None:
            features["coinglass_orderbook_depth_imbalance_usd"] = float(bid or 0.0) - float(ask or 0.0)
            features["coinglass_orderbook_trust_delta"] = 0.0
    actual = bool(features)
    return {
        "schema_version": "coinglass_normalized_payload_v1",
        "provider": "coinglass",
        "endpoint_id": spec.endpoint_id,
        "feature_family": spec.group,
        "symbol": symbol,
        "event_time": _event_time(row),
        "generated_at": _now(),
        "features": features,
        "actual_payload_present": actual,
        "heartbeat_only": not actual,
        "core_system_blocked": False,
        "raw_key_exposed": False,
    }


def _funding_row_for_symbol(data: Any, symbol: str) -> Mapping[str, Any] | None:
    """Pick the Binance stablecoin-margin funding entry for our coin."""
    coin = str(symbol).upper()
    if coin.endswith("USDT"):
        coin = coin[:-4]
    if not isinstance(data, list):
        return None
    for entry in data:
        if not isinstance(entry, Mapping) or str(entry.get("symbol")).upper() != coin:
            continue
        margin_list = entry.get("stablecoin_margin_list") or []
        binance = [
            m for m in margin_list
            if isinstance(m, Mapping) and str(m.get("exchange")).lower() == "binance"
        ]
        if binance:
            return binance[0]
        return margin_list[0] if isinstance(margin_list, list) and margin_list and isinstance(margin_list[0], Mapping) else None
    return None


def _data(payload: Any) -> Any:
    if isinstance(payload, Mapping):
        data = payload.get("data")
        if isinstance(data, Mapping) and "data" in data:
            return data.get("data")
        return data if data is not None else payload
    return payload


def _last_row(data: Any) -> Mapping[str, Any]:
    if isinstance(data, list) and data:
        row = data[-1]
        return row if isinstance(row, Mapping) else {}
    return data if isinstance(data, Mapping) else {}


def _first_float(row: Mapping[str, Any], *fields: str) -> float | None:
    for field in fields:
        try:
            value = row.get(field)
            if value is None:
                continue
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _optional_deltas(row: Mapping[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for source, dest in (
        ("open_interest_change_percent_5m", "coinglass_open_interest_delta_usd_5m"),
        ("open_interest_change_percent_1h", "coinglass_open_interest_delta_usd_1h"),
    ):
        value = _first_float(row, source)
        if value is not None:
            out[dest] = value
    if out:
        out["coinglass_oi_price_divergence_score"] = 0.0
    return out


def _event_time(row: Mapping[str, Any]) -> str | None:
    raw = row.get("time") or row.get("timestamp")
    try:
        if raw is not None:
            ts = float(raw)
            if ts > 10_000_000_000:
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    except (TypeError, ValueError, OSError):
        return None
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
