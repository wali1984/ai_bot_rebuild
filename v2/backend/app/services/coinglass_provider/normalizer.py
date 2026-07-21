"""CoinGlass payload to feature mapping."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from app.services.coinglass_provider.endpoint_registry import CoinGlassEndpointSpec


def normalize_coinglass_payload(
    *,
    spec: CoinGlassEndpointSpec,
    symbol: str,
    payload: Any,
    observed_at: str | datetime | None = None,
) -> dict[str, Any]:
    observed_dt = _observation_time(observed_at)
    data = _data(payload)
    source_interval = spec.source_interval
    bar_open: datetime | None = None
    bar_close: datetime | None = None
    source_age_seconds: float | None = None
    source_fresh: bool | None = None
    history_row_admission = "NOT_HISTORICAL"
    if source_interval:
        (
            row,
            bar_open,
            bar_close,
            source_age_seconds,
            history_row_admission,
        ) = _latest_closed_row(
            data,
            interval=source_interval,
            observed_at=observed_dt,
            max_source_age_seconds=spec.max_source_age_seconds,
        )
        source_fresh = history_row_admission == "LATEST_CLOSED_ROW"
    else:
        row = _last_row(data)
    features: dict[str, float] = {}
    if spec.group == "funding_rate":
        # v4 exchange-list returns ALL coins; each row is
        # {symbol, stablecoin_margin_list: [{exchange, funding_rate,
        #  next_funding_time}, ...], token_margin_list: [...]}.
        row = _funding_row_for_symbol(data, symbol) or {}
        rate = _percentage_fraction(
            row,
            "funding_rate",
            "fundingRate",
            "close",
            minimum=-100.0,
            maximum=100.0,
        )
        if rate is not None:
            features["coinglass_funding_rate"] = rate
        next_funding = _timestamp_from_fields(row, "next_funding_time", "nextFundingTime")
        if next_funding is not None and next_funding >= observed_dt:
            features["coinglass_next_funding_minutes"] = (
                next_funding - observed_dt
            ).total_seconds() / 60.0
    elif spec.group == "open_interest":
        # The documented first row has exchange="All" and is the aggregate
        # across venues.  List order is not a stable selection contract.
        row = _aggregate_open_interest_row(data)
        oi = _bounded_float(
            row,
            "open_interest_usd",
            "openInterestUsd",
            "open_interest",
            "close",
            minimum=0.0,
        )
        if oi is not None:
            features["coinglass_open_interest_usd"] = oi
        features.update(_optional_open_interest_changes(row))
    elif spec.group == "long_short_ratio":
        long_fraction = _percentage_fraction(
            row,
            "top_account_long_percent",
            "longAccount",
            "long_ratio",
            minimum=0.0,
            maximum=100.0,
        )
        short_fraction = _percentage_fraction(
            row,
            "top_account_short_percent",
            "shortAccount",
            "short_ratio",
            minimum=0.0,
            maximum=100.0,
        )
        ratio = _bounded_float(
            row,
            "top_account_long_short_ratio",
            "longShortRatio",
            "long_short_ratio",
            minimum=0.0,
            maximum=1_000.0,
        )
        if (
            long_fraction is not None
            and short_fraction is not None
            and abs((long_fraction + short_fraction) - 1.0) <= 0.02
        ):
            features["coinglass_long_ratio"] = long_fraction
            features["coinglass_short_ratio"] = short_fraction
        if ratio is not None:
            features["coinglass_long_short_extreme_score"] = min(1.0, abs(ratio - 1.0) / 2.0)
    elif spec.group == "liquidation_orders":
        buy = _bounded_float(
            row,
            "aggregated_short_liquidation_usd",
            "shortLiquidationUsd",
            "buy_usd",
            minimum=0.0,
        )
        sell = _bounded_float(
            row,
            "aggregated_long_liquidation_usd",
            "longLiquidationUsd",
            "sell_usd",
            minimum=0.0,
        )
        if buy is not None and sell is not None:
            total = buy + sell
            imbalance = buy - sell
            if math.isfinite(total) and math.isfinite(imbalance):
                features["coinglass_liquidation_buy_usd_1h"] = buy
                features["coinglass_liquidation_sell_usd_1h"] = sell
                features["coinglass_liquidation_total_usd_1h"] = total
                features["coinglass_liquidation_imbalance_usd"] = imbalance
    elif spec.group == "liquidation_heatmap_or_levels":
        above = _bounded_float(
            row,
            "nearest_above_usd",
            "liquidation_level_above_usd",
            minimum=0.0,
        )
        below = _bounded_float(
            row,
            "nearest_below_usd",
            "liquidation_level_below_usd",
            minimum=0.0,
        )
        if above is not None:
            features["coinglass_nearest_liq_zone_above_usd"] = above
        if below is not None:
            features["coinglass_nearest_liq_zone_below_usd"] = below
        if above is not None and below is not None:
            features["coinglass_liq_zone_distance_usd"] = abs(above - below)
    elif spec.group == "market_snapshot":
        # v4 pairs-markets returns one row per exchange instrument; pick the
        # requested Binance perp row for price/24h-change and aggregate volume
        # across every returned instrument/venue for broad market activity.
        rows = data if isinstance(data, list) else []
        exch_rows = [r for r in rows if isinstance(r, Mapping)]
        binance = [
            r for r in exch_rows
            if str(r.get("exchange_name")).strip().casefold() == "binance"
        ]
        primary = _market_primary_row(binance, symbol)
        price = _bounded_float(
            primary,
            "current_price",
            "price_usd",
            "price",
            minimum=0.0,
        )
        if price is not None:
            features["coinglass_price_usd"] = price
        change = _percentage_fraction(
            primary,
            "price_change_percent_24h",
            "price_change_24h_pct",
            minimum=-1_000_000.0,
            maximum=1_000_000.0,
        )
        if change is not None:
            features["coinglass_price_change_24h_fraction"] = change
        volumes = [
            v for v in (
                _bounded_float(
                    r,
                    "volume_usd",
                    "volume_24h_usd",
                    "turnover_usd",
                    minimum=0.0,
                )
                for r in exch_rows
            )
            if v is not None
        ]
        total_volume = float(sum(volumes)) if volumes else None
        if total_volume is not None and math.isfinite(total_volume):
            features["coinglass_volume_24h_usd"] = total_volume
            features["coinglass_market_snapshot_volume_usd"] = total_volume
        if exch_rows:
            exchange_names = {
                str(r.get("exchange_name")).strip()
                for r in exch_rows
                if str(r.get("exchange_name") or "").strip()
            }
            if exchange_names:
                features["coinglass_exchange_count"] = float(len(exchange_names))
    elif spec.group == "trades":
        buy = _bounded_float(
            row,
            "taker_buy_volume_usd",
            "aggressive_buy_usd",
            "buy_usd",
            minimum=0.0,
        )
        sell = _bounded_float(
            row,
            "taker_sell_volume_usd",
            "aggressive_sell_usd",
            "sell_usd",
            minimum=0.0,
        )
        if buy is not None and sell is not None:
            imbalance = buy - sell
            if math.isfinite(imbalance):
                features["coinglass_trade_imbalance_usd"] = imbalance
    elif spec.group == "orderbook_l2_l3":
        bid = _bounded_float(
            row,
            "bid_usd",
            "bids_usd",
            "bidVolume",
            minimum=0.0,
        )
        ask = _bounded_float(
            row,
            "ask_usd",
            "asks_usd",
            "askVolume",
            minimum=0.0,
        )
        if bid is not None and ask is not None:
            imbalance = bid - ask
            if math.isfinite(imbalance):
                features["coinglass_orderbook_depth_imbalance_usd"] = imbalance

    actual = bool(features)
    historical = source_interval is not None
    closed = bool(
        historical
        and bar_open is not None
        and bar_close is not None
        and bar_close <= observed_dt
    )
    temporal_contract_valid = actual and (
        not historical or (closed and source_fresh is True)
    )
    event_dt = bar_open if historical else _event_datetime(row)
    feature_cutoff = bar_close if historical and closed else observed_dt if actual else None
    return {
        "schema_version": "coinglass_normalized_payload_v2",
        "provider": "coinglass",
        "endpoint_id": spec.endpoint_id,
        "feature_family": spec.group,
        "symbol": symbol,
        "event_time": _iso(event_dt),
        "feature_cutoff": _iso(feature_cutoff),
        "source_interval": source_interval,
        "bar_open": _iso(bar_open),
        "bar_close": _iso(bar_close),
        "is_closed": closed if historical else None,
        "source_age_seconds": source_age_seconds,
        "max_source_age_seconds": spec.max_source_age_seconds,
        "source_fresh": source_fresh,
        "temporal_contract_valid": temporal_contract_valid,
        "history_row_admission": history_row_admission,
        "generated_at": _iso(observed_dt),
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
            if isinstance(m, Mapping)
            and str(m.get("exchange")).strip().casefold() == "binance"
        ]
        if binance:
            return binance[0]
        return None
    return None


def _market_primary_row(
    rows: list[Mapping[str, Any]],
    symbol: str,
) -> Mapping[str, Any]:
    requested = _normalized_instrument(symbol)
    base, quote = _base_quote(requested)
    for row in rows:
        instrument_id = _normalized_instrument(
            row.get("instrument_id") or row.get("instrumentId")
        )
        if instrument_id == requested:
            return row
    for row in rows:
        row_symbol = _normalized_instrument(
            row.get("symbol") or row.get("pair") or row.get("instrument")
        )
        row_base = _normalized_instrument(
            row.get("base_asset") or row.get("baseAsset") or row.get("base_currency")
        )
        row_quote = _normalized_instrument(
            row.get("quote_asset")
            or row.get("quoteAsset")
            or row.get("quote_currency")
        )
        if row_symbol == requested or (
            base and quote and row_base == base and row_quote == quote
        ):
            return row
    return {}


def _normalized_instrument(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _base_quote(symbol: str) -> tuple[str, str]:
    for quote in ("USDT", "USDC", "BUSD", "USD"):
        if symbol.endswith(quote) and len(symbol) > len(quote):
            return symbol[: -len(quote)], quote
    return "", ""


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
            if value is None or isinstance(value, bool):
                continue
            parsed = float(value)
            if math.isfinite(parsed):
                return parsed
        except (TypeError, ValueError):
            continue
    return None


def _bounded_float(
    row: Mapping[str, Any],
    *fields: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    value = _first_float(row, *fields)
    if value is None:
        return None
    if minimum is not None and value < minimum:
        return None
    if maximum is not None and value > maximum:
        return None
    return value


def _percentage_fraction(
    row: Mapping[str, Any],
    *fields: str,
    minimum: float,
    maximum: float,
) -> float | None:
    value = _bounded_float(row, *fields, minimum=minimum, maximum=maximum)
    return None if value is None else value / 100.0


def _optional_open_interest_changes(row: Mapping[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for source, dest in (
        (
            "open_interest_change_percent_5m",
            "coinglass_open_interest_change_fraction_5m",
        ),
        (
            "open_interest_change_percent_1h",
            "coinglass_open_interest_change_fraction_1h",
        ),
    ):
        value = _percentage_fraction(
            row,
            source,
            minimum=-10_000.0,
            maximum=10_000.0,
        )
        if value is not None:
            out[dest] = value
    return out


def _aggregate_open_interest_row(data: Any) -> Mapping[str, Any]:
    if not isinstance(data, list):
        return {}
    for row in data:
        if not isinstance(row, Mapping):
            continue
        exchange = row.get("exchange") or row.get("exchange_name")
        if str(exchange or "").strip().casefold() == "all":
            return row
    return {}


def _latest_closed_row(
    data: Any,
    *,
    interval: str,
    observed_at: datetime,
    max_source_age_seconds: int | None,
) -> tuple[
    Mapping[str, Any],
    datetime | None,
    datetime | None,
    float | None,
    str,
]:
    interval_seconds = _interval_seconds(interval)
    if interval_seconds is None or not isinstance(data, list):
        return {}, None, None, None, "NO_CLOSED_ROW"
    candidates: list[tuple[datetime, datetime, Mapping[str, Any]]] = []
    for row in data:
        if not isinstance(row, Mapping):
            continue
        opened_at = _event_datetime(row)
        if opened_at is None:
            continue
        closed_at = opened_at + timedelta(seconds=interval_seconds)
        if closed_at <= observed_at:
            candidates.append((opened_at, closed_at, row))
    if not candidates:
        return {}, None, None, None, "NO_CLOSED_ROW"
    opened_at, closed_at, row = max(candidates, key=lambda item: item[0])
    source_age_seconds = max(0.0, (observed_at - closed_at).total_seconds())
    if (
        max_source_age_seconds is None
        or isinstance(max_source_age_seconds, bool)
        or max_source_age_seconds <= 0
    ):
        return (
            {},
            opened_at,
            closed_at,
            source_age_seconds,
            "SOURCE_AGE_CONTRACT_INVALID",
        )
    if source_age_seconds > max_source_age_seconds:
        return (
            {},
            opened_at,
            closed_at,
            source_age_seconds,
            "CLOSED_ROW_TOO_OLD",
        )
    return row, opened_at, closed_at, source_age_seconds, "LATEST_CLOSED_ROW"


def _interval_seconds(interval: str) -> int | None:
    match = re.fullmatch(r"([1-9][0-9]*)([mhdw])", str(interval).strip().lower())
    if match is None:
        return None
    count = int(match.group(1))
    multiplier = {
        "m": 60,
        "h": 60 * 60,
        "d": 24 * 60 * 60,
        "w": 7 * 24 * 60 * 60,
    }[match.group(2)]
    return count * multiplier


def _timestamp_from_fields(row: Mapping[str, Any], *fields: str) -> datetime | None:
    for field in fields:
        parsed = _timestamp(row.get(field))
        if parsed is not None:
            return parsed
    return None


def _event_datetime(row: Mapping[str, Any]) -> datetime | None:
    return _timestamp_from_fields(row, "time", "timestamp")


def _timestamp(raw: Any) -> datetime | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        timestamp = float(raw)
    except (TypeError, ValueError):
        if not isinstance(raw, str):
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        result = parsed.astimezone(UTC)
    else:
        if not math.isfinite(timestamp):
            return None
        if abs(timestamp) > 10_000_000_000:
            timestamp /= 1000.0
        try:
            result = datetime.fromtimestamp(timestamp, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if result.year < 2009 or result.year > 2100:
        return None
    return result


def _observation_time(value: str | datetime | None) -> datetime:
    if isinstance(value, datetime):
        parsed = value
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    parsed_timestamp = _timestamp(value)
    return parsed_timestamp if parsed_timestamp is not None else datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
