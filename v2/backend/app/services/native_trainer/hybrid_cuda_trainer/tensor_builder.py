"""V2 unified feature tensor builder with explicit masks."""
from __future__ import annotations

import hashlib
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

FEATURE_SPEC: tuple[tuple[str, str], ...] = (
    ("last_price", "v2:market:prices"),
    ("mark_price", "v2:market:prices"),
    ("index_price", "v2:market:prices"),
    ("basis_pct", "v2:market:prices"),
    ("funding_rate", "v2:market:funding"),
    ("open_interest", "v2:market:open_interest"),
    ("oi_change_pct", "v2:market:open_interest_hist"),
    ("long_short_ratio", "v2:market:long_short"),
    ("long_account_ratio", "v2:market:long_short"),
    ("short_account_ratio", "v2:market:long_short"),
    ("quote_volume", "v2:market:ohlcv"),
    ("volume", "v2:market:ohlcv"),
    ("volatility", "v2:features:latest"),
    ("volatility_pct", "v2:features:latest"),
    ("open", "v2:market:ohlcv"),
    ("high", "v2:market:ohlcv"),
    ("low", "v2:market:ohlcv"),
    ("close", "v2:market:ohlcv"),
    ("num_trades", "v2:market:ohlcv"),
    ("taker_buy_base_vol", "v2:market:ohlcv"),
    ("taker_buy_quote_vol", "v2:market:ohlcv"),
    ("taker_sell_base_vol", "v2:market:ohlcv"),
    ("taker_sell_quote_vol", "v2:market:ohlcv"),
    ("taker_buy_ratio", "v2:market:ohlcv"),
    ("taker_sell_ratio", "v2:market:ohlcv"),
    ("ob_best_bid", "v2:market:orderbook"),
    ("ob_best_ask", "v2:market:orderbook"),
    ("ob_mid_price", "v2:market:orderbook"),
    ("ob_spread_bps", "v2:market:orderbook"),
    ("ob_imbalance", "v2:market:orderbook"),
    ("orderbook_depth_usd", "v2:market:orderbook"),
    ("depth_total_usd", "v2:market:orderbook"),
    ("depth_usd", "v2:market:orderbook"),
    ("depth_vs_tape_divergence", "v2:market:microstructure"),
    ("RSI", "v2:features:ta"),
    ("MACD", "v2:features:ta"),
    ("MACD_signal", "v2:features:ta"),
    ("MACD_hist", "v2:features:ta"),
    ("ATR", "v2:features:ta"),
    ("EMA_12", "v2:features:ta"),
    ("EMA_26", "v2:features:ta"),
    ("bollinger_upper", "v2:features:ta"),
    ("bollinger_middle", "v2:features:ta"),
    ("bollinger_lower", "v2:features:ta"),
    ("bollinger_width_pct", "v2:features:ta"),
    ("liquidation_long_level", "v2:market:liquidation_levels"),
    ("liquidation_short_level", "v2:market:liquidation_levels"),
    ("nearest_liquidation_level_above", "v2:market:liquidation_levels"),
    ("nearest_liquidation_level_below", "v2:market:liquidation_levels"),
    ("distance_to_long_liq_bps", "v2:market:liquidation_levels"),
    ("distance_to_short_liq_bps", "v2:market:liquidation_levels"),
    ("liquidation_cluster_strength_long", "v2:market:liquidation_levels"),
    ("liquidation_cluster_strength_short", "v2:market:liquidation_levels"),
    ("liquidation_distance_pct", "v2:market:liquidation_levels"),
    ("liquidation_strength", "v2:market:liquidation_levels"),
    ("liquidation_cascade_risk", "v2:market:liquidation_levels"),
    ("liquidation_pressure_direction", "v2:market:liquidation_levels"),
    ("liquidity_zone_above", "v2:market:liquidity_zones"),
    ("liquidity_zone_below", "v2:market:liquidity_zones"),
    ("distance_to_liquidity_zone_bps", "v2:market:liquidity_zones"),
    ("orderbook_wall_strength", "v2:market:orderbook"),
    ("microstructure_liquidity_depth", "v2:market:microstructure"),
    ("coinapi_wsds_tape_imbalance", "v2:market:microstructure"),
    ("last_liq_bps_24h", "v2:liquidations:events"),
    ("liquidation_is_stale", "v2:market:liquidation_levels"),
    ("liquidation_sweep_target_long", "v2:liquidations:levels"),
    ("liquidation_sweep_target_short", "v2:liquidations:levels"),
    ("liquidation_sweep_target_long_distance_bps", "v2:liquidations:levels"),
    ("liquidation_sweep_target_short_distance_bps", "v2:liquidations:levels"),
    ("liquidation_zones_long_count", "v2:liquidations:levels"),
    ("liquidation_zones_short_count", "v2:liquidations:levels"),
    ("liquidation_count_1h", "v2:market:liquidations:aggregate"),
    ("liquidation_notional_1h", "v2:market:liquidations:aggregate"),
    ("liquidation_direction_bias_1h", "v2:market:liquidations:aggregate"),
    ("microprice", "v2:market:microstructure"),
    ("spread", "v2:market:orderbook"),
    ("micro_volatility", "v2:market:microstructure"),
    ("toxicity_proxy", "v2:market:microstructure"),
    ("tape_imbalance", "v2:market:microstructure"),
    ("order_flow_imbalance", "v2:market:microstructure"),
    ("public_intel_score", "v2:altdata:public_intel"),
    ("nansen_score", "v2:altdata:nansen"),
    ("lunarcrush_score", "v2:altdata:lunarcrush"),
    ("aicoin_score", "v2:altdata:aicoin"),
    ("whale_wall_score", "v2:altdata:whale_walls"),
    ("coingecko_score", "v2:altdata:symbol_score"),
    ("surf_score", "v2:altdata:symbol_score"),
    ("defillama_score", "v2:altdata:public_intel"),
    ("fear_greed_context", "v2:altdata:public_intel"),
    ("mempool_context", "v2:altdata:public_intel"),
    ("price_last", "v2:market:prices"),
    ("ohlcv_close", "v2:market:ohlcv"),
    ("ohlcv_volume", "v2:market:ohlcv"),
    ("orderbook_spread_bps", "v2:market:orderbook"),
    ("orderbook_depth_imbalance", "v2:market:orderbook"),
    ("open_interest_change_pct", "v2:market:open_interest_hist"),
    ("liquidation_count_5m", "v2:liquidations:events"),
    ("liquidation_level_distance_bps", "v2:market:liquidation_levels"),
    ("ret_pct", "v2:features:latest"),
    ("log_return", "v2:features:latest"),
    ("range_pct", "v2:features:latest"),
    ("body_pct", "v2:features:latest"),
    ("true_range_pct", "v2:features:latest"),
    ("ema_12", "v2:features:latest"),
    ("ema_26", "v2:features:latest"),
    ("rsi_14", "v2:features:latest"),
    ("macd", "v2:features:latest"),
    ("macd_signal", "v2:features:latest"),
    ("macd_hist", "v2:features:latest"),
    ("bb_width_pct", "v2:features:latest"),
    ("htf_ret_pct", "v2:features:latest"),
    ("htf_rsi_14", "v2:features:latest"),
    ("bid_ask_spread_bps", "v2:features:latest"),
    ("depth_imbalance", "v2:features:latest"),
    ("micro_price", "v2:market:microstructure"),
    ("paper_position_present", "v2:paper:positions"),
    ("paper_unrealized_bps", "v2:paper:positions"),
    ("risk_recent_allow_rate", "v2:risk:decisions"),
    ("orchestrator_recent_allow_rate", "v2:orchestrator:decisions"),
    ("altdata_symbol_score", "v2:altdata:symbol_score"),
    ("provider_availability_score", "v2:altdata:symbol_score"),
    ("altdata_freshness_score", "v2:altdata:symbol_score"),
    ("coingecko_discovery_score", "v2:altdata:symbol_score"),
    ("coingecko_liquidity_score", "v2:altdata:symbol_score"),
    ("coingecko_momentum_score", "v2:altdata:symbol_score"),
    ("surf_market_price_signal_score", "v2:altdata:symbol_score"),
    ("coinglass_derivatives_score", "v2:altdata:symbol_score"),
    ("public_intel_score", "v2:altdata:public_intel"),
    ("defillama_liquidity_score", "v2:altdata:public_intel"),
    ("defillama_tvl_momentum_score", "v2:altdata:public_intel"),
    ("news_attention_score", "v2:altdata:public_intel"),
    ("news_sentiment_score", "v2:altdata:public_intel"),
    ("fear_greed_score", "v2:altdata:public_intel"),
    ("btc_mempool_pressure_score", "v2:altdata:public_intel"),
    ("aicoin_market_activity_score", "v2:altdata:aicoin"),
    ("aicoin_coin_profile_score", "v2:altdata:aicoin"),
    ("aicoin_order_flow_score", "v2:altdata:aicoin"),
    ("aicoin_whale_order_score", "v2:altdata:aicoin"),
    ("aicoin_signal_score", "v2:altdata:aicoin"),
    ("aicoin_drop_radar_score", "v2:altdata:aicoin"),
    ("aicoin_airdrop_score", "v2:altdata:aicoin"),
    ("aicoin_liquidation_score", "v2:altdata:aicoin"),
    ("aicoin_open_interest_score", "v2:altdata:aicoin"),
    ("aicoin_news_attention_score", "v2:altdata:aicoin"),
    ("whale_wall_score", "v2:altdata:whale_walls"),
    ("whale_bid_pressure_score", "v2:altdata:whale_walls"),
    ("whale_ask_pressure_score", "v2:altdata:whale_walls"),
    ("whale_wall_imbalance_score", "v2:altdata:whale_walls"),
    ("whale_wall_count_score", "v2:altdata:whale_walls"),
    ("whale_wall_event_count", "v2:altdata:whale_walls"),
    ("whale_bid_wall_notional_usd", "v2:altdata:whale_walls"),
    ("whale_ask_wall_notional_usd", "v2:altdata:whale_walls"),
    ("whale_total_wall_notional_usd", "v2:altdata:whale_walls"),
    ("nearest_bid_wall_distance_bps", "v2:altdata:whale_walls"),
    ("nearest_ask_wall_distance_bps", "v2:altdata:whale_walls"),
    ("lunarcrush_score", "v2:altdata:lunarcrush"),
    ("nansen_presence", "v2:altdata:nansen"),
)


@dataclass(frozen=True)
class FeatureTensorRecord:
    tensor_id: str
    symbol: str
    timeframe: str
    feature_snapshot_id: str
    values: tuple[float, ...]
    missing_mask: tuple[int, ...]
    stale_mask: tuple[int, ...]
    source_availability: tuple[int, ...]
    feature_names: tuple[str, ...]
    source_labels: tuple[str, ...]
    missing_feature_names: tuple[str, ...]
    stale_feature_names: tuple[str, ...]
    data_coverage_percent: float
    source_availability_vector: tuple[int, ...]

    @property
    def model_vector(self) -> tuple[float, ...]:
        return (
            self.values
            + tuple(float(v) for v in self.missing_mask)
            + tuple(float(v) for v in self.stale_mask)
            + tuple(float(v) for v in self.source_availability)
        )


def _finite_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        out = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def _dig(payload: Mapping[str, Any] | None, *keys: str) -> Any:
    if not isinstance(payload, Mapping):
        return None
    for key in keys:
        cur: Any = payload
        for part in key.split("."):
            if not isinstance(cur, Mapping):
                cur = None
                break
            cur = cur.get(part)
        if cur is not None:
            return cur
    return None


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _parse_ms(value: Any) -> int | None:
    try:
        if value is None:
            return None
        parsed = float(value)
    except (TypeError, ValueError):
        if isinstance(value, str):
            try:
                return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
            except ValueError:
                return None
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    number = int(parsed)
    return number * 1000 if abs(number) < 10_000_000_000 else number


def _now_ms() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


def _kline_close_ms(row: Any) -> int | None:
    if isinstance(row, Mapping):
        return _parse_ms(
            _first_present(
                row.get("close_time"),
                row.get("candle_close_time"),
                row.get("closeTime"),
                row.get("T"),
            )
        )
    if isinstance(row, (list, tuple)) and len(row) >= 7:
        return _parse_ms(row[6])
    return None


def _binance_row_to_mapping(row: tuple[Any, ...] | list[Any]) -> Mapping[str, Any]:
    return {
        "open": row[1],
        "high": row[2],
        "low": row[3],
        "close": row[4],
        "volume": row[5],
        "close_time": row[6],
        "quote_volume": row[7],
        "num_trades": row[8],
        "taker_buy_base_vol": row[9],
        "taker_buy_quote_vol": row[10],
        "candle_closed_confirmed": True,
    }


def _latest_kline(ohlcv: Any) -> Mapping[str, Any]:
    allow_unknown = os.environ.get("PIPELINE_TRUST_ALLOW_UNKNOWN_KLINE_FINALITY", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if isinstance(ohlcv, Mapping):
        finality = _first_present(
            ohlcv.get("closed_candle"),
            ohlcv.get("is_closed"),
            ohlcv.get("candle_closed_confirmed"),
        )
        if finality is not True and not allow_unknown:
            return {}
        return ohlcv
    if isinstance(ohlcv, list) and ohlcv:
        selected = None
        for candidate in reversed(ohlcv):
            if isinstance(candidate, Mapping):
                finality = _first_present(
                    candidate.get("closed_candle"),
                    candidate.get("is_closed"),
                    candidate.get("candle_closed_confirmed"),
                )
                if finality is True:
                    selected = candidate
                    break
                continue
            if allow_unknown and isinstance(candidate, (list, tuple)) and len(candidate) >= 11:
                selected = candidate
                break
        row = selected if selected is not None else ohlcv[-1]
        if isinstance(row, Mapping):
            finality = _first_present(
                row.get("closed_candle"),
                row.get("is_closed"),
                row.get("candle_closed_confirmed"),
            )
            if finality is not True and not allow_unknown:
                return {}
            return row
        if isinstance(row, (list, tuple)) and len(row) >= 11:
            if not allow_unknown:
                return {}
            return {
                "open": row[1],
                "high": row[2],
                "low": row[3],
                "close": row[4],
                "volume": row[5],
                "quote_volume": row[7],
                "num_trades": row[8],
                "taker_buy_base_vol": row[9],
                "taker_buy_quote_vol": row[10],
            }
    return {}


def _oi_change_pct(open_interest_hist: Any) -> float | None:
    if isinstance(open_interest_hist, Mapping):
        direct = _finite_float(_dig(open_interest_hist, "change_pct", "oi_change_pct"))
        if direct is not None:
            return direct
        return None
    if not isinstance(open_interest_hist, list) or len(open_interest_hist) < 2:
        return None
    first = open_interest_hist[0]
    last = open_interest_hist[-1]
    if not isinstance(first, Mapping) or not isinstance(last, Mapping):
        return None
    first_oi = _finite_float(_first_present(first.get("sumOpenInterest"), first.get("openInterest"), first.get("open_interest")))
    last_oi = _finite_float(_first_present(last.get("sumOpenInterest"), last.get("openInterest"), last.get("open_interest")))
    if first_oi is None or first_oi == 0.0 or last_oi is None:
        return None
    return (last_oi - first_oi) / first_oi


def _best_book_side(orderbook: Any, side: str) -> tuple[float | None, float | None]:
    if not isinstance(orderbook, Mapping):
        return None, None
    price = _finite_float(_dig(orderbook, f"best_{side}", f"{side}_price", side))
    size = _finite_float(_dig(orderbook, f"best_{side}_size", f"{side}_size", f"{side}_qty"))
    rows = orderbook.get(f"{side}s")
    if price is None and isinstance(rows, list) and rows:
        first = rows[0]
        if isinstance(first, Mapping):
            price = _finite_float(_first_present(first.get("price"), first.get("p")))
            size = _finite_float(_first_present(first.get("qty"), first.get("quantity"), first.get("size"), first.get("q")))
        elif isinstance(first, (list, tuple)) and len(first) >= 2:
            price = _finite_float(first[0])
            size = _finite_float(first[1])
    return price, size


def _book_depth_usd(orderbook: Any) -> float | None:
    if not isinstance(orderbook, Mapping):
        return None
    explicit = _finite_float(
        _first_present(
            _dig(orderbook, "orderbook_depth_usd"),
            _dig(orderbook, "depth_total_usd"),
            _dig(orderbook, "depth_usd"),
        )
    )
    if explicit is not None:
        return explicit
    total = 0.0
    seen = False
    for side in ("bid", "ask"):
        rows = orderbook.get(f"{side}s")
        if not isinstance(rows, list):
            continue
        for row in rows[:25]:
            if isinstance(row, Mapping):
                px = _finite_float(_first_present(row.get("price"), row.get("p")))
                qty = _finite_float(_first_present(row.get("qty"), row.get("quantity"), row.get("size"), row.get("q")))
            elif isinstance(row, (list, tuple)) and len(row) >= 2:
                px = _finite_float(row[0])
                qty = _finite_float(row[1])
            else:
                px = None
                qty = None
            if px is not None and qty is not None:
                total += px * qty
                seen = True
    return total if seen else None


def _ta_value(*payloads: Any, names: tuple[str, ...]) -> Any:
    for payload in payloads:
        if not isinstance(payload, Mapping):
            continue
        indicators = payload.get("indicators") if isinstance(payload.get("indicators"), Mapping) else None
        features = payload.get("features") if isinstance(payload.get("features"), Mapping) else None
        for source in (indicators, features, payload):
            if not isinstance(source, Mapping):
                continue
            for name in names:
                if name in source:
                    return source[name]
    return None


def _coinank_data(payload: Any) -> Any:
    if not isinstance(payload, Mapping):
        return None
    data: Any = payload.get("data")
    for _ in range(4):
        if isinstance(data, Mapping) and "data" in data and (
            "success" in data or "code" in data or isinstance(data.get("data"), (Mapping, list))
        ):
            data = data.get("data")
            continue
        break
    return data


def _coinank_last_row(payload: Any) -> Any:
    data = _coinank_data(payload)
    if isinstance(data, list) and data:
        return data[-1]
    return data


def _coinank_last_float(payload: Any, names: tuple[str, ...], indexes: tuple[int, ...] = ()) -> float | None:
    row = _coinank_last_row(payload)
    if isinstance(row, Mapping):
        for name in names:
            value = row.get(name)
            if isinstance(value, list) and value:
                parsed = _finite_float(value[-1])
            else:
                parsed = _finite_float(value)
            if parsed is not None:
                return parsed
    if isinstance(row, (list, tuple)):
        for index in indexes:
            if len(row) > index:
                parsed = _finite_float(row[index])
                if parsed is not None:
                    return parsed
    data = _coinank_data(payload)
    if isinstance(data, Mapping):
        for name in names:
            value = data.get(name)
            if isinstance(value, list) and value:
                parsed = _finite_float(value[-1])
            else:
                parsed = _finite_float(value)
            if parsed is not None:
                return parsed
    return None


def _coinank_oi_change_pct(payload: Any) -> float | None:
    data = _coinank_data(payload)
    if not isinstance(data, list) or len(data) < 2:
        return None
    first = data[0]
    last = data[-1]
    if not isinstance(first, Mapping) or not isinstance(last, Mapping):
        return None
    first_oi = _finite_float(_first_present(first.get("coinValue"), first.get("close"), first.get("volume")))
    last_oi = _finite_float(_first_present(last.get("coinValue"), last.get("close"), last.get("volume")))
    if first_oi in (None, 0.0) or last_oi is None:
        return None
    return (last_oi - float(first_oi)) / float(first_oi)


def _coinank_liquidation_turnover(payload: Any) -> float | None:
    row = _coinank_last_row(payload)
    if not isinstance(row, Mapping):
        return None
    long_turn = _finite_float(row.get("longTurnover"))
    short_turn = _finite_float(row.get("shortTurnover"))
    if long_turn is None and short_turn is None:
        return None
    return float(long_turn or 0.0) + float(short_turn or 0.0)


def _coinank_order_flow_imbalance(payload: Any) -> float | None:
    row = _coinank_last_row(payload)
    buy_value: float | None = None
    sell_value: float | None = None
    if isinstance(row, (list, tuple)) and len(row) >= 3:
        buy_value = _finite_float(row[1])
        sell_value = _finite_float(row[2])
    elif isinstance(row, Mapping):
        buy_value = _finite_float(_first_present(row.get("buy"), row.get("buyValue"), row.get("buyCount")))
        sell_value = _finite_float(_first_present(row.get("sell"), row.get("sellValue"), row.get("sellCount")))
    if buy_value is None or sell_value is None:
        return None
    denom = buy_value + sell_value
    if denom <= 0:
        return None
    return (buy_value - sell_value) / denom


class V2UnifiedFeatureTensorBuilder:
    """Assemble model tensors from V2-owned payloads.

    Missing numeric values are represented as ``0.0`` only with
    ``missing_mask[i] == 1``. Staleness is carried independently.
    """

    feature_spec = FEATURE_SPEC

    def build(
        self,
        *,
        symbol: str,
        timeframe: str,
        payloads: Mapping[str, Any],
    ) -> FeatureTensorRecord:
        latest = payloads.get("features_latest")
        latest_features = latest.get("features") if isinstance(latest, Mapping) else None
        ta = payloads.get("features_ta")
        ta_indicators = ta.get("indicators") if isinstance(ta, Mapping) else None
        ta_full = payloads.get("features_ta_full")
        technical_analysis = payloads.get("technical_analysis")
        ohlcv = _latest_kline(payloads.get("ohlcv"))
        orderbook = payloads.get("orderbook")
        micro = payloads.get("microstructure")
        liquidation_levels = payloads.get("liquidation_levels")
        liquidity_zones = payloads.get("liquidity_zones")
        coinank_oi_payload = payloads.get("coinank_open_interest")
        coinank_funding_payload = payloads.get("coinank_funding")
        coinank_long_short_payload = payloads.get("coinank_long_short")
        coinank_liquidations_payload = payloads.get("coinank_liquidations")
        coinank_flow_payload = payloads.get("coinank_market_order_flow")
        paper_positions = payloads.get("paper_positions")
        risk = payloads.get("risk_decisions")
        orchestrator = payloads.get("orchestrator_decisions")
        symbol_score = payloads.get("symbol_score")
        public_intel = payloads.get("public_intel")
        aicoin = payloads.get("aicoin")
        whale_walls = payloads.get("whale_walls")
        bid_px, bid_qty = _best_book_side(orderbook, "bid")
        ask_px, ask_qty = _best_book_side(orderbook, "ask")
        mid = None if bid_px is None or ask_px is None else (bid_px + ask_px) / 2.0
        spread_bps = None if bid_px is None or ask_px is None or bid_px <= 0 else ((ask_px - bid_px) / bid_px) * 10000.0
        book_imbalance = None
        if bid_qty is not None and ask_qty is not None and (bid_qty + ask_qty) > 0:
            book_imbalance = (bid_qty - ask_qty) / (bid_qty + ask_qty)
        ohlcv_volume = _finite_float(_first_present(_dig(ohlcv, "volume", "v"), _dig(latest_features, "volume")))
        quote_volume = _finite_float(
            _first_present(
                _dig(ohlcv, "quote_volume", "quoteVolume", "quote_asset_volume"),
                _dig(payloads.get("prices"), "ticker_24hr.quoteVolume"),
            )
        )
        taker_buy_base = _finite_float(_dig(ohlcv, "taker_buy_base_vol", "takerBuyBaseVolume", "taker_buy_base_asset_volume"))
        taker_buy_quote = _finite_float(_dig(ohlcv, "taker_buy_quote_vol", "takerBuyQuoteVolume", "taker_buy_quote_asset_volume"))
        taker_sell_base = None if ohlcv_volume is None or taker_buy_base is None else max(0.0, ohlcv_volume - taker_buy_base)
        taker_sell_quote = None if quote_volume is None or taker_buy_quote is None else max(0.0, quote_volume - taker_buy_quote)
        taker_buy_ratio = None
        if ohlcv_volume == 0.0 and taker_buy_base == 0.0:
            taker_buy_ratio = 0.0
        elif ohlcv_volume not in (None, 0.0) and taker_buy_base is not None:
            taker_buy_ratio = taker_buy_base / ohlcv_volume
        taker_sell_ratio = None if taker_buy_ratio is None else max(0.0, 1.0 - taker_buy_ratio)
        if ohlcv_volume == 0.0 and taker_buy_base == 0.0:
            taker_sell_ratio = 0.0
        kline_high = _finite_float(_dig(ohlcv, "high", "h"))
        kline_low = _finite_float(_dig(ohlcv, "low", "l"))
        kline_open = _finite_float(_dig(ohlcv, "open", "o"))
        kline_close = _finite_float(_dig(ohlcv, "close", "c"))
        kline_range_pct = None
        if kline_high is not None and kline_low is not None and kline_close not in (None, 0.0):
            kline_range_pct = (kline_high - kline_low) / float(kline_close)
        kline_body_pct = None
        if kline_open is not None and kline_close not in (None, 0.0):
            kline_body_pct = abs(kline_close - kline_open) / float(kline_close)
        mark_price = _finite_float(_dig(payloads.get("prices"), "funding.markPrice", "mark_price", "markPrice"))
        index_price = _finite_float(_dig(payloads.get("prices"), "funding.indexPrice", "index_price", "indexPrice"))
        basis_pct = None
        if mark_price is not None and index_price not in (None, 0.0):
            basis_pct = (mark_price - float(index_price)) / float(index_price)
        oi_change_pct = _oi_change_pct(payloads.get("open_interest_hist"))
        coinank_open_interest = _coinank_last_float(
            coinank_oi_payload,
            ("open_interest", "openInterest", "sumOpenInterest", "coinValue", "close", "volume"),
            (4, 3, 1),
        )
        coinank_oi_change_pct = _coinank_oi_change_pct(coinank_oi_payload)
        coinank_funding_rate = _coinank_last_float(
            coinank_funding_payload,
            ("fundingRate", "fr", "funding_rate", "rate"),
            (1, 2),
        )
        coinank_long_short_ratio = _coinank_last_float(
            coinank_long_short_payload,
            ("longShortRatio", "long_short_ratio", "longRatio", "ratio", "close"),
            (1,),
        )
        coinank_liquidation_turnover = _coinank_liquidation_turnover(coinank_liquidations_payload)
        coinank_order_flow_imbalance = _coinank_order_flow_imbalance(coinank_flow_payload)
        liq_long_distance = _finite_float(_dig(liquidation_levels, "liquidation_long_distance_pct", "long_distance_pct"))
        liq_short_distance = _finite_float(_dig(liquidation_levels, "liquidation_short_distance_pct", "short_distance_pct"))
        liq_long_distance_bps = _finite_float(
            _first_present(
                _dig(liquidation_levels, "distance_to_long_liq_bps", "long_distance_bps"),
                None if liq_long_distance is None else liq_long_distance * 100.0,
            )
        )
        liq_short_distance_bps = _finite_float(
            _first_present(
                _dig(liquidation_levels, "distance_to_short_liq_bps", "short_distance_bps"),
                None if liq_short_distance is None else liq_short_distance * 100.0,
            )
        )
        liq_distance_candidates = [
            value for value in (liq_long_distance, liq_short_distance) if value is not None
        ]
        liq_nearest_distance = min(liq_distance_candidates) if liq_distance_candidates else None
        liq_long_strength = _finite_float(_dig(liquidation_levels, "liquidation_long_strength", "long_strength"))
        liq_short_strength = _finite_float(_dig(liquidation_levels, "liquidation_short_strength", "short_strength"))
        liq_strength_candidates = [
            value for value in (liq_long_strength, liq_short_strength) if value is not None
        ]
        liq_strength = max(liq_strength_candidates) if liq_strength_candidates else None
        # Per-symbol WSS aggregate (count_1h, notional_1h, direction_bias_1h)
        liquidations_agg = payloads.get("liquidations_agg")

        raw_by_name: dict[str, Any] = {
            "last_price": _dig(payloads.get("prices"), "ticker_24hr.lastPrice", "price", "last", "last_price"),
            "mark_price": mark_price,
            "index_price": index_price,
            "basis_pct": _first_present(_dig(payloads.get("prices"), "basis_pct", "funding.basis_pct"), basis_pct),
            "price_last": _dig(payloads.get("prices"), "ticker_24hr.lastPrice", "price", "last", "last_price"),
            "open": _dig(ohlcv, "open", "o"),
            "high": _dig(ohlcv, "high", "h"),
            "low": _dig(ohlcv, "low", "l"),
            "close": _dig(ohlcv, "close", "c"),
            "ohlcv_close": _dig(ohlcv, "close", "c"),
            "volume": ohlcv_volume,
            "ohlcv_volume": ohlcv_volume,
            "quote_volume": quote_volume,
            "num_trades": _dig(ohlcv, "num_trades", "numberOfTrades", "n"),
            "taker_buy_base_vol": taker_buy_base,
            "taker_buy_quote_vol": taker_buy_quote,
            "taker_sell_base_vol": taker_sell_base,
            "taker_sell_quote_vol": taker_sell_quote,
            "taker_buy_ratio": taker_buy_ratio,
            "taker_sell_ratio": taker_sell_ratio,
            "ob_best_bid": bid_px,
            "ob_best_ask": ask_px,
            "ob_mid_price": mid,
            "ob_spread_bps": _first_present(_dig(orderbook, "ob_spread_bps", "spread_bps", "bid_ask_spread_bps"), spread_bps),
            "ob_imbalance": _first_present(_dig(orderbook, "ob_imbalance", "depth_imbalance"), book_imbalance),
            "orderbook_depth_usd": _book_depth_usd(orderbook),
            "depth_total_usd": _book_depth_usd(orderbook),
            "depth_usd": _book_depth_usd(orderbook),
            "depth_vs_tape_divergence": _dig(micro, "depth_vs_tape_divergence"),
            "orderbook_spread_bps": _first_present(_dig(orderbook, "spread_bps", "bid_ask_spread_bps"), spread_bps),
            "orderbook_depth_imbalance": _first_present(_dig(orderbook, "depth_imbalance"), book_imbalance),
            "funding_rate": _first_present(
                _dig(payloads.get("funding"), "funding_rate", "rate", "fundingRate", "lastFundingRate"),
                coinank_funding_rate,
            ),
            "open_interest": _first_present(
                _dig(payloads.get("open_interest"), "open_interest", "oi", "openInterest", "sumOpenInterest"),
                coinank_open_interest,
            ),
            "oi_change_pct": _first_present(
                _dig(payloads.get("open_interest_hist"), "change_pct", "oi_change_pct"),
                oi_change_pct,
                coinank_oi_change_pct,
            ),
            "long_short_ratio": _first_present(
                _dig(payloads.get("long_short"), "long_short_ratio", "longShortRatio"),
                _dig(latest_features, "long_short_ratio"),
                coinank_long_short_ratio,
            ),
            "long_account_ratio": _first_present(
                _dig(payloads.get("long_short"), "long_account_ratio", "longAccount"),
                _dig(latest_features, "long_account_ratio"),
            ),
            "short_account_ratio": _first_present(
                _dig(payloads.get("long_short"), "short_account_ratio", "shortAccount"),
                _dig(latest_features, "short_account_ratio"),
            ),
            "open_interest_change_pct": _first_present(
                _dig(payloads.get("open_interest_hist"), "change_pct", "oi_change_pct"),
                oi_change_pct,
                coinank_oi_change_pct,
            ),
            "volatility": _first_present(
                _dig(latest_features, "volatility", "ccxt_volatility_1m", "ccxt_volatility", "true_range_pct"),
                kline_range_pct,
            ),
            "volatility_pct": _first_present(
                _dig(latest_features, "volatility_pct", "true_range_pct", "range_pct"),
                kline_range_pct,
            ),
            "RSI": _ta_value(latest, ta, ta_full, technical_analysis, names=("RSI", "rsi_14", "ta_RSI_14", "ta_RSI")),
            "MACD": _ta_value(latest, ta, ta_full, technical_analysis, names=("MACD", "macd", "ta_MACD_12_26_9_macd", "ta_MACD_macd")),
            "MACD_signal": _ta_value(latest, ta, ta_full, technical_analysis, names=("MACD_signal", "macd_signal", "ta_MACD_12_26_9_signal", "ta_MACD_macdsignal")),
            "MACD_hist": _ta_value(latest, ta, ta_full, technical_analysis, names=("MACD_hist", "macd_hist", "ta_MACD_12_26_9_hist", "ta_MACD_macdhist")),
            "ATR": _ta_value(latest, ta, ta_full, technical_analysis, names=("ATR", "atr_14", "ta_ATR_14", "ta_ATR")),
            "EMA_12": _ta_value(latest, ta, ta_full, technical_analysis, names=("EMA_12", "ema_12", "ta_EMA_12")),
            "EMA_26": _ta_value(latest, ta, ta_full, technical_analysis, names=("EMA_26", "ema_26", "ta_EMA_26")),
            "bollinger_upper": _ta_value(latest, ta, ta_full, technical_analysis, names=("bollinger_upper", "bb_upper", "ta_BBANDS_20_upper", "ta_BBANDS_upperband")),
            "bollinger_middle": _ta_value(latest, ta, ta_full, technical_analysis, names=("bollinger_middle", "bb_middle", "ta_BBANDS_20_middle", "ta_BBANDS_middleband")),
            "bollinger_lower": _ta_value(latest, ta, ta_full, technical_analysis, names=("bollinger_lower", "bb_lower", "ta_BBANDS_20_lower", "ta_BBANDS_lowerband")),
            "bollinger_width_pct": _ta_value(latest, ta, ta_full, technical_analysis, names=("bollinger_width_pct", "bb_width_pct", "bb_width")),
            "liquidation_count_5m": _first_present(
                _dig(liquidation_levels, "liquidation_count_5m"),
                _dig(payloads.get("liquidations"), "count_5m", "event_count"),
                None if coinank_liquidation_turnover is None else (1.0 if coinank_liquidation_turnover > 0 else 0.0),
            ),
            "liquidation_long_level": _dig(liquidation_levels, "long_level", "liquidation_long_level"),
            "liquidation_short_level": _dig(liquidation_levels, "short_level", "liquidation_short_level"),
            "nearest_liquidation_level_above": _first_present(
                _dig(liquidation_levels, "nearest_liquidation_level_above", "level_above"),
            ),
            "nearest_liquidation_level_below": _first_present(
                _dig(liquidation_levels, "nearest_liquidation_level_below", "level_below"),
            ),
            "distance_to_long_liq_bps": liq_long_distance_bps,
            "distance_to_short_liq_bps": liq_short_distance_bps,
            "liquidation_cluster_strength_long": _first_present(
                _dig(liquidation_levels, "liquidation_cluster_strength_long", "long_cluster_strength"),
                liq_long_strength,
            ),
            "liquidation_cluster_strength_short": _first_present(
                _dig(liquidation_levels, "liquidation_cluster_strength_short", "short_cluster_strength"),
                liq_short_strength,
            ),
            "liquidation_distance_pct": _first_present(
                _dig(liquidation_levels, "distance_pct", "liquidation_distance_pct"),
                liq_nearest_distance,
            ),
            "liquidation_strength": _first_present(
                _dig(liquidation_levels, "strength", "liquidation_strength"),
                liq_strength,
            ),
            "liquidation_cascade_risk": _first_present(
                _dig(liquidation_levels, "liquidation_cascade_risk", "cascade_risk"),
            ),
            "liquidation_pressure_direction": _first_present(
                _dig(liquidation_levels, "liquidation_pressure_direction", "pressure_direction"),
            ),
            "liquidation_sweep_target_long": _dig(liquidation_levels, "liquidation_sweep_target_long", "sweep_target_long"),
            "liquidation_sweep_target_short": _dig(liquidation_levels, "liquidation_sweep_target_short", "sweep_target_short"),
            "liquidation_sweep_target_long_distance_bps": _dig(liquidation_levels, "liquidation_sweep_target_long_distance_bps", "sweep_long_dist_bps"),
            "liquidation_sweep_target_short_distance_bps": _dig(liquidation_levels, "liquidation_sweep_target_short_distance_bps", "sweep_short_dist_bps"),
            "liquidation_zones_long_count": _dig(liquidation_levels, "liquidation_zones_count_long", "zones_count_long"),
            "liquidation_zones_short_count": _dig(liquidation_levels, "liquidation_zones_count_short", "zones_count_short"),
            "liquidation_count_1h": _dig(liquidations_agg, "count_1h"),
            "liquidation_notional_1h": _dig(liquidations_agg, "notional_1h"),
            "liquidation_direction_bias_1h": _dig(liquidations_agg, "direction_bias_1h"),
            "liquidity_zone_above": _dig(liquidity_zones, "liquidity_zone_above", "nearest_liquidity_zone_above", "zone_above"),
            "liquidity_zone_below": _dig(liquidity_zones, "liquidity_zone_below", "nearest_liquidity_zone_below", "zone_below"),
            "distance_to_liquidity_zone_bps": _dig(liquidity_zones, "distance_to_liquidity_zone_bps", "liquidity_distance_bps"),
            "orderbook_wall_strength": _first_present(
                _dig(orderbook, "orderbook_wall_strength", "wall_strength"),
                _dig(whale_walls, "whale_wall_strength", "whale_wall_score"),
            ),
            "microstructure_liquidity_depth": _first_present(
                _dig(micro, "microstructure_liquidity_depth", "liquidity_depth", "depth_usd"),
                _book_depth_usd(orderbook),
            ),
            "coinapi_wsds_tape_imbalance": _first_present(
                _dig(micro, "coinapi_wsds_tape_imbalance", "wsds_tape_imbalance"),
                coinank_order_flow_imbalance,
            ),
            "last_liq_bps_24h": _first_present(
                _dig(payloads.get("liquidations"), "last_liq_bps_24h", "liq_bps_24h"),
                _dig(latest_features, "last_liq_bps_24h"),
                _dig(liquidation_levels, "last_liq_bps_proxy"),
                coinank_liquidation_turnover,
            ),
            "liquidation_is_stale": _dig(liquidation_levels, "is_stale", "liquidation_is_stale"),
            "liquidation_level_distance_bps": _first_present(
                _dig(liquidation_levels, "nearest_distance_bps"),
                None if liq_nearest_distance is None else liq_nearest_distance * 100.0,
            ),
            "microprice": _dig(micro, "microprice", "micro_price"),
            "spread": _first_present(_dig(orderbook, "spread", "spread_bps"), spread_bps),
            "micro_volatility": _first_present(
                _dig(micro, "volatility", "micro_volatility"),
                _dig(latest_features, "micro_volatility"),
                kline_range_pct,
            ),
            "toxicity_proxy": _first_present(
                _dig(micro, "toxicity_proxy"),
                None if _finite_float(_dig(micro, "imbalance_5")) is None else abs(float(_dig(micro, "imbalance_5"))),
            ),
            "tape_imbalance": _first_present(_dig(micro, "tape_imbalance"), coinank_order_flow_imbalance),
            "order_flow_imbalance": _first_present(_dig(micro, "order_flow_imbalance", "ofi"), coinank_order_flow_imbalance),
            "paper_position_present": _dig(paper_positions, "position_present", "paper_position_present"),
            "paper_unrealized_bps": _dig(paper_positions, "unrealized_bps", "paper_unrealized_bps"),
            "risk_recent_allow_rate": _dig(risk, "recent_allow_rate", "allow_rate"),
            "orchestrator_recent_allow_rate": _dig(orchestrator, "recent_allow_rate", "allow_rate"),
            "altdata_symbol_score": _dig(symbol_score, "altdata_symbol_score"),
            "provider_availability_score": _dig(symbol_score, "provider_availability_score"),
            "altdata_freshness_score": _dig(symbol_score, "altdata_freshness_score"),
            "coingecko_discovery_score": _dig(symbol_score, "coingecko_discovery_score"),
            "coingecko_liquidity_score": _dig(symbol_score, "coingecko_liquidity_score"),
            "coingecko_momentum_score": _dig(symbol_score, "coingecko_momentum_score"),
            "surf_market_price_signal_score": _dig(symbol_score, "surf_market_price_signal_score"),
            "coinglass_derivatives_score": _dig(symbol_score, "coinglass_derivatives_score"),
            "public_intel_score": _first_present(_dig(public_intel, "score", "public_intel_score"), _dig(symbol_score, "public_intel_score")),
            "defillama_liquidity_score": _first_present(_dig(public_intel, "defillama_liquidity_score"), _dig(symbol_score, "defillama_liquidity_score")),
            "defillama_tvl_momentum_score": _first_present(_dig(public_intel, "defillama_tvl_momentum_score"), _dig(symbol_score, "defillama_tvl_momentum_score")),
            "news_attention_score": _first_present(_dig(public_intel, "news_attention_score"), _dig(symbol_score, "news_attention_score")),
            "news_sentiment_score": _first_present(_dig(public_intel, "news_sentiment_score"), _dig(symbol_score, "news_sentiment_score")),
            "fear_greed_score": _first_present(_dig(public_intel, "fear_greed_score"), _dig(symbol_score, "fear_greed_score")),
            "btc_mempool_pressure_score": _first_present(_dig(public_intel, "btc_mempool_pressure_score"), _dig(symbol_score, "btc_mempool_pressure_score")),
            "aicoin_market_activity_score": _first_present(_dig(aicoin, "aicoin_market_activity_score"), _dig(symbol_score, "aicoin_market_activity_score")),
            "aicoin_coin_profile_score": _first_present(_dig(aicoin, "aicoin_coin_profile_score"), _dig(symbol_score, "aicoin_coin_profile_score")),
            "aicoin_order_flow_score": _first_present(_dig(aicoin, "aicoin_order_flow_score"), _dig(symbol_score, "aicoin_order_flow_score")),
            "aicoin_whale_order_score": _first_present(_dig(aicoin, "aicoin_whale_order_score"), _dig(symbol_score, "aicoin_whale_order_score")),
            "aicoin_signal_score": _first_present(_dig(aicoin, "aicoin_signal_score"), _dig(symbol_score, "aicoin_signal_score")),
            "aicoin_drop_radar_score": _first_present(_dig(aicoin, "aicoin_drop_radar_score"), _dig(symbol_score, "aicoin_drop_radar_score")),
            "aicoin_airdrop_score": _first_present(_dig(aicoin, "aicoin_airdrop_score"), _dig(symbol_score, "aicoin_airdrop_score")),
            "aicoin_liquidation_score": _first_present(_dig(aicoin, "aicoin_liquidation_score"), _dig(symbol_score, "aicoin_liquidation_score")),
            "aicoin_open_interest_score": _first_present(_dig(aicoin, "aicoin_open_interest_score"), _dig(symbol_score, "aicoin_open_interest_score")),
            "aicoin_news_attention_score": _first_present(_dig(aicoin, "aicoin_news_attention_score"), _dig(symbol_score, "aicoin_news_attention_score")),
            "whale_wall_score": _first_present(_dig(whale_walls, "whale_wall_score"), _dig(symbol_score, "whale_wall_score")),
            "whale_bid_pressure_score": _first_present(_dig(whale_walls, "whale_bid_pressure_score"), _dig(symbol_score, "whale_bid_pressure_score")),
            "whale_ask_pressure_score": _first_present(_dig(whale_walls, "whale_ask_pressure_score"), _dig(symbol_score, "whale_ask_pressure_score")),
            "whale_wall_imbalance_score": _first_present(_dig(whale_walls, "whale_wall_imbalance_score"), _dig(symbol_score, "whale_wall_imbalance_score")),
            "whale_wall_count_score": _first_present(_dig(whale_walls, "whale_wall_count_score"), _dig(symbol_score, "whale_wall_count_score")),
            "whale_wall_event_count": _first_present(_dig(whale_walls, "whale_wall_event_count"), _dig(symbol_score, "whale_wall_event_count")),
            "whale_bid_wall_notional_usd": _first_present(_dig(whale_walls, "whale_bid_wall_notional_usd"), _dig(symbol_score, "whale_bid_wall_notional_usd")),
            "whale_ask_wall_notional_usd": _first_present(_dig(whale_walls, "whale_ask_wall_notional_usd"), _dig(symbol_score, "whale_ask_wall_notional_usd")),
            "whale_total_wall_notional_usd": _first_present(_dig(whale_walls, "whale_total_wall_notional_usd"), _dig(symbol_score, "whale_total_wall_notional_usd")),
            "nearest_bid_wall_distance_bps": _first_present(_dig(whale_walls, "nearest_bid_wall_distance_bps"), _dig(symbol_score, "nearest_bid_wall_distance_bps")),
            "nearest_ask_wall_distance_bps": _first_present(_dig(whale_walls, "nearest_ask_wall_distance_bps"), _dig(symbol_score, "nearest_ask_wall_distance_bps")),
            "lunarcrush_score": _dig(payloads.get("lunarcrush"), "score", "lunarcrush_score"),
            "nansen_presence": _dig(payloads.get("nansen"), "presence", "nansen_presence"),
            "nansen_score": _dig(payloads.get("nansen"), "score", "nansen_score", "presence", "nansen_presence"),
            "aicoin_score": _first_present(_dig(aicoin, "score", "aicoin_score"), _dig(symbol_score, "aicoin_score"), _dig(aicoin, "aicoin_signal_score")),
            "coingecko_score": _first_present(_dig(symbol_score, "coingecko_score"), _dig(symbol_score, "coingecko_discovery_score")),
            "surf_score": _first_present(_dig(symbol_score, "surf_score"), _dig(symbol_score, "surf_market_price_signal_score")),
            "defillama_score": _first_present(_dig(public_intel, "defillama_score"), _dig(public_intel, "defillama_liquidity_score"), _dig(symbol_score, "defillama_score")),
            "fear_greed_context": _first_present(_dig(public_intel, "fear_greed_context"), _dig(public_intel, "fear_greed_score"), _dig(symbol_score, "fear_greed_score")),
            "mempool_context": _first_present(_dig(public_intel, "mempool_context"), _dig(public_intel, "btc_mempool_pressure_score"), _dig(symbol_score, "btc_mempool_pressure_score")),
        }
        for name, _source in FEATURE_SPEC:
            if name in raw_by_name:
                continue
            raw_by_name[name] = _dig(latest_features, name) or _dig(latest, name) or _dig(ta_indicators, name)
        raw_by_name["bid_ask_spread_bps"] = raw_by_name["bid_ask_spread_bps"] or raw_by_name["orderbook_spread_bps"]
        raw_by_name["depth_imbalance"] = raw_by_name["depth_imbalance"] or raw_by_name["orderbook_depth_imbalance"]
        raw_by_name["micro_price"] = raw_by_name["micro_price"] or _dig(micro, "micro_price")
        raw_by_name["toxicity_proxy"] = raw_by_name["toxicity_proxy"] or _dig(latest_features, "toxicity_proxy") or _dig(micro, "toxicity_proxy")
        if raw_by_name.get("range_pct") is None:
            raw_by_name["range_pct"] = kline_range_pct
        if raw_by_name.get("body_pct") is None:
            raw_by_name["body_pct"] = kline_body_pct
        if raw_by_name.get("true_range_pct") is None:
            raw_by_name["true_range_pct"] = kline_range_pct
        if raw_by_name.get("ret_pct") is None and kline_open not in (None, 0.0) and kline_close is not None:
            raw_by_name["ret_pct"] = (kline_close - float(kline_open)) / float(kline_open)
        if raw_by_name.get("log_return") is None and kline_open not in (None, 0.0) and kline_close not in (None, 0.0):
            raw_by_name["log_return"] = math.log(float(kline_close) / float(kline_open))

        coinank_sources: dict[str, str] = {}
        if coinank_funding_rate is not None and _dig(payloads.get("funding"), "funding_rate", "rate", "fundingRate", "lastFundingRate") is None:
            coinank_sources["funding_rate"] = "latest:coinank:funding"
        if coinank_open_interest is not None and _dig(payloads.get("open_interest"), "open_interest", "oi", "openInterest", "sumOpenInterest") is None:
            coinank_sources["open_interest"] = "latest:coinank:open_interest"
        if coinank_oi_change_pct is not None and _dig(payloads.get("open_interest_hist"), "change_pct", "oi_change_pct") is None and oi_change_pct is None:
            coinank_sources["oi_change_pct"] = "latest:coinank:open_interest"
            coinank_sources["open_interest_change_pct"] = "latest:coinank:open_interest"
        if coinank_long_short_ratio is not None and _dig(payloads.get("long_short"), "long_short_ratio", "longShortRatio") is None and _dig(latest_features, "long_short_ratio") is None:
            coinank_sources["long_short_ratio"] = "latest:coinank:long_short"
        if coinank_liquidation_turnover is not None:
            if _dig(payloads.get("liquidations"), "count_5m", "event_count") is None:
                coinank_sources["liquidation_count_5m"] = "latest:coinank:liquidations"
            if _dig(payloads.get("liquidations"), "last_liq_bps_24h", "liq_bps_24h") is None and _dig(latest_features, "last_liq_bps_24h") is None:
                coinank_sources["last_liq_bps_24h"] = "latest:coinank:liquidations"
        if coinank_order_flow_imbalance is not None:
            if _dig(micro, "tape_imbalance") is None:
                coinank_sources["tape_imbalance"] = "latest:coinank:market_order_flow"
            if _dig(micro, "order_flow_imbalance", "ofi") is None:
                coinank_sources["order_flow_imbalance"] = "latest:coinank:market_order_flow"

        stale_input_flags = set()
        for payload in payloads.values():
            if isinstance(payload, Mapping):
                for flag in payload.get("stale_feature_flags") or payload.get("stale_flags") or ():
                    stale_input_flags.add(str(flag))
        latest_stale_state = str(_dig(latest, "feature_freshness_state", "freshness_state") or "").upper()

        values: list[float] = []
        missing_mask: list[int] = []
        stale_mask: list[int] = []
        source_availability: list[int] = []
        missing_names: list[str] = []
        stale_names: list[str] = []
        for name, source in FEATURE_SPEC:
            val = _finite_float(raw_by_name.get(name))
            missing = val is None
            stale = name in stale_input_flags or latest_stale_state in {"STALE", "MISSING_OR_STALE"}
            values.append(0.0 if missing else float(val))
            missing_mask.append(1 if missing else 0)
            stale_mask.append(1 if stale else 0)
            source_availability.append(0 if missing else 1)
            if missing:
                missing_names.append(name)
            if stale:
                stale_names.append(name)

        available = len(values) - sum(missing_mask)
        coverage = 100.0 * available / max(1, len(values))
        snapshot_id = str(
            _dig(latest, "feature_snapshot_id")
            or _dig(ta, "feature_snapshot_id")
            or f"{symbol}:{timeframe}:no_feature_snapshot"
        )
        tensor_id = "v2_hybrid_tensor_" + hashlib.sha256(
            f"{symbol}|{timeframe}|{snapshot_id}|{values}|{missing_mask}|{stale_mask}".encode()
        ).hexdigest()[:32]
        return FeatureTensorRecord(
            tensor_id=tensor_id,
            symbol=symbol,
            timeframe=timeframe,
            feature_snapshot_id=snapshot_id,
            values=tuple(values),
            missing_mask=tuple(missing_mask),
            stale_mask=tuple(stale_mask),
            source_availability=tuple(source_availability),
            feature_names=tuple(name for name, _ in FEATURE_SPEC),
            source_labels=tuple(coinank_sources.get(name, source) for name, source in FEATURE_SPEC),
            missing_feature_names=tuple(missing_names),
            stale_feature_names=tuple(stale_names),
            data_coverage_percent=float(coverage),
            source_availability_vector=tuple(source_availability),
        )
