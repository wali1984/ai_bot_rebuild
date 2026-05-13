"""
ULTRA-LOW-LATENCY DUAL-SPEED FEATURE PIPELINE
Ensures real-time data for trading and training without compromising system resources

ARCHITECTURE:
- Fast Lane: 1m/5m timeframes for BTC/ETH/SOL → 15-30s refresh (trading critical)
- Slow Lane: All other combinations → 5min refresh (context/analysis)
- Real-time price updates: Direct from websocket (no caching)
"""
import time
import json
import threading
import concurrent.futures
import logging
from typing import Dict, Any, List, Tuple
import redis
from config import REDIS_URL, TIMEFRAMES
try:
    from config import ENABLE_CROSS_TF_FEATURES, CROSS_TF_SIGNAL_FIELDS
except ImportError:
    ENABLE_CROSS_TF_FEATURES = False
    CROSS_TF_SIGNAL_FIELDS = []
from datetime import datetime

# Dynamic symbol loading - supports hot-reload without restart
try:
    from utils.symbol_manager import get_symbols_cached
    SYMBOLS = get_symbols_cached()
except ImportError:
    from config import SYMBOLS

# Configure logging with both console and file output
log_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
log_filename = f'logs/feature_pipeline_dual_{log_timestamp}.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(),  # Console output
        logging.FileHandler(log_filename)  # File output with timestamp
    ]
)

logger = logging.getLogger(__name__)
logger.info(f"📝 Logging to: {log_filename}")

logger = logging.getLogger("DualSpeedFeaturePipeline")

class FeatureAggregator:
    """
    Minimal, self-contained feature aggregator used by DualSpeedFeaturePipeline.

    NOTE:
    - Does NOT use TokenMetrics (policy).
    - Pulls TA-Lib indicators from Redis `ta:{symbol}:{tf}` hashes.
    - Writes `ind_ta_*` and `ind_ind_{symbol}_ta_*` keys expected by the rest of the system.
    """

    def __init__(self, redis_client: redis.Redis | None = None, *args, **kwargs):
        # Backwards-compat: older FeatureAggregator variants accepted extra kwargs
        # (e.g., update_interval). DualSpeedFeaturePipeline may pass those through.
        self.redis = redis_client or redis.Redis.from_url(REDIS_URL, decode_responses=True)

    @staticmethod
    def _safe_float(x: Any, default: float = 0.0) -> float:
        try:
            if x is None or x == "":
                return float(default)
            return float(x)
        except Exception:
            return float(default)

    def _get_market_ohlcv(self, symbol: str, tf: str) -> Dict[str, Any]:
        """Fetch OHLCV (best-effort) from `market:{symbol}:{tf}` JSON."""
        try:
            raw = self.redis.get(f"market:{symbol}:{tf}")
            if raw:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
        except Exception:
            pass
        return {}

    def _get_orderbook_top(self, symbol: str) -> Dict[str, Any]:
        """Fetch top-of-book snapshot from `orderbook:top:{symbol}` JSON."""
        try:
            raw = self.redis.get(f"orderbook:top:{symbol}")
            if raw:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
        except Exception:
            pass
        return {}

    def _get_binance_mark(self, symbol: str) -> Dict[str, Any]:
        """Fetch mark/index/basis/funding payload."""
        try:
            raw = self.redis.get(f"latest:binance:mark_price:{symbol}")
            if raw:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
        except Exception:
            pass
        try:
            raw = self.redis.get(f"latest:binance:premium_index:{symbol}")
            if raw:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
        except Exception:
            pass
        return {}

    def _get_ta_hash(self, symbol: str, tf: str) -> Dict[str, Any]:
        """TA-Lib indicators are stored as Redis hash under `ta:{symbol}:{tf}`."""
        try:
            d = self.redis.hgetall(f"ta:{symbol}:{tf}")
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def aggregate_symbol_tf(self, symbol: str, tf: str) -> Dict[str, Any]:
        """Build unified features dict for a given symbol+tf (for Redis HSET)."""
        now_ms = int(time.time() * 1000)
        features: Dict[str, Any] = {
            "symbol": symbol,
            "tf": tf,
            "ts_ms": str(now_ms),
        }

        # OHLCV
        ohlcv = self._get_market_ohlcv(symbol, tf)
        o = self._safe_float(ohlcv.get("open"))
        h = self._safe_float(ohlcv.get("high"))
        l = self._safe_float(ohlcv.get("low"))
        c = self._safe_float(ohlcv.get("close"))
        v = self._safe_float(ohlcv.get("volume"))
        if o > 0:
            features[f"ccxt_price_change_{tf}_pct"] = str(((c - o) / o) * 100.0 if c > 0 else 0.0)
        if c > 0:
            features[f"ccxt_volatility_{tf}"] = str((h - l) / c if h > 0 and l > 0 else 0.0)
        features["ccxt_open"] = str(o)
        features["ccxt_high"] = str(h)
        features["ccxt_low"] = str(l)
        features["ccxt_close"] = str(c)
        features["ccxt_volume"] = str(v)

        # Orderbook imbalance (simple)
        ob = self._get_orderbook_top(symbol)
        try:
            # Support both:
            # - CCXT-like schema: {"bids":[[px,sz],...], "asks":[[px,sz],...]}
            # - Binance fast schema (string key): {"bid":..., "ask":..., "spread":..., "imbalance":...}

            if isinstance(ob, dict) and ("bid" in ob and "ask" in ob):
                bid_px = self._safe_float(ob.get("bid"))
                ask_px = self._safe_float(ob.get("ask"))
                features["ob_best_bid"] = str(bid_px)
                features["ob_best_ask"] = str(ask_px)
                if bid_px > 0 and ask_px > 0:
                    features["ob_ob_mid_price"] = str((bid_px + ask_px) / 2.0)
                    features["ob_ob_spread_bps"] = str(((ask_px - bid_px) / bid_px) * 10000.0)
                if ob.get("imbalance") is not None:
                    features["ob_ob_imbalance"] = str(self._safe_float(ob.get("imbalance")))
            else:
                bids = ob.get("bids") or []
                asks = ob.get("asks") or []
                if bids and asks and isinstance(bids[0], (list, tuple)) and isinstance(asks[0], (list, tuple)):
                    bid_px = self._safe_float(bids[0][0])
                    bid_sz = self._safe_float(bids[0][1])
                    ask_px = self._safe_float(asks[0][0])
                    ask_sz = self._safe_float(asks[0][1])
                    denom = (bid_sz + ask_sz) if (bid_sz + ask_sz) > 0 else 1.0
                    features["ob_ob_imbalance"] = str((bid_sz - ask_sz) / denom)
                    features["ob_best_bid"] = str(bid_px)
                    features["ob_best_ask"] = str(ask_px)
                    if bid_px > 0 and ask_px > 0:
                        features["ob_ob_mid_price"] = str((bid_px + ask_px) / 2.0)
                        features["ob_ob_spread_bps"] = str(((ask_px - bid_px) / bid_px) * 10000.0)
        except Exception:
            pass

        # Binance mark/index/basis/funding
        mark = self._get_binance_mark(symbol)
        if mark:
            if mark.get("mark_price") is not None:
                features["mark_price"] = str(mark.get("mark_price"))
            if mark.get("index_price") is not None:
                features["index_price"] = str(mark.get("index_price"))
            if mark.get("basis_pct") is not None:
                features["basis_pct"] = str(mark.get("basis_pct"))
            if mark.get("last_funding_rate") is not None:
                features["funding_rate"] = str(mark.get("last_funding_rate"))

        # TA-Lib indicators
        ta = self._get_ta_hash(symbol, tf)
        if ta:
            features[f"ind_ind_{symbol}_timestamp"] = str(now_ms)
            for k, v in ta.items():
                if not isinstance(k, str) or not k.startswith("ta_"):
                    continue
                try:
                    fv = self._safe_float(v, default=None)  # type: ignore[arg-type]
                    if fv is None:
                        continue
                    features[f"ind_{k}"] = str(fv)  # ind_ta_*
                    features[f"ind_ind_{symbol}_{k}"] = str(fv)
                except Exception:
                    continue

        # Pressure (derived, bounded)
        pressure = 0.0
        try:
            pressure = self._safe_float(features.get("ind_ta_pressure", 0.0))
        except Exception:
            pressure = 0.0
        if pressure == 0.0 and o > 0:
            chg_pct = ((c - o) / o) * 100.0 if c > 0 else 0.0
            pressure = max(-1.0, min(1.0, chg_pct / 2.0))  # 2% move ~ full pressure
        features["ind_ta_pressure"] = str(pressure)
        if tf == "1m":
            features["ind_ind_1m_pressure"] = str(pressure)
        elif tf == "5m":
            features["ind_ind_5m_pressure"] = str(pressure)
        elif tf == "15m":
            features["ind_ind_15m_pressure"] = str(pressure)
        elif tf == "1h":
            features["ind_ind_1h_pressure"] = str(pressure)

        # ------------------------------------------------------------------
        # CoinAnk features (near-real-time): ingest/live_coinank.py writes
        # `features:coinank:{family}:{symbol}:{exchange}:{tf}:latest` JSON records.
        #
        # We copy only flattened numeric `coinank_*` fields into unified_features
        # so the trainer can consume them deterministically.
        # ------------------------------------------------------------------
        try:
            exchange = "Binance"

            # Prefer endpoint-specific keys to avoid family-level collisions (some siblings can fail and overwrite).
            coinank_endpoints = (
                # Liquidations
                "liquidation_history",
                "liquidation_aggregated_history",

                # Open interest
                "openInterest_kline",
                "openInterest_symbol_Chart",

                # Market order flow (high-signal; list-of-lists now flattened by live_coinank)
                "marketOrder_getBuySellVolume",
                "marketOrder_getBuySellValue",
                "marketOrder_getBuySellCount",

                # Funding / long-short
                "fundingRate_kline",
                "fundingRate_indicator",
                "ls_global_account_ratio",
                "ls_toptrader_accounts",

                # Advanced
                "orderFlow_lists",
                "netPositions_getNetPositions",
            )

            coinank_families = ("liquidations", "market_order_flow", "funding", "long_short", "advanced", "open_interest")

            keys = []
            # Endpoint-specific first
            for ep in coinank_endpoints:
                keys.append(f"features:coinank_endpoint:{ep}:{symbol}:{exchange}:{tf}:latest")
            # Family-level as fallback
            for fam in coinank_families:
                keys.append(f"features:coinank:{fam}:{symbol}:{exchange}:{tf}:latest")

            raws = self.redis.mget(keys)
            for kname, raw in zip(keys, raws):
                if not raw:
                    continue
                try:
                    rec = json.loads(raw)
                except Exception:
                    continue
                if not isinstance(rec, dict):
                    continue

                # Freshness as a feature (model can learn to discount stale sources)
                try:
                    ts_src = rec.get("timestamp") or rec.get("ts_epoch_ms") or rec.get("ts_ms")
                    if ts_src is not None:
                        st_ms = max(0, now_ms - int(float(ts_src)))
                        # make key stable and low-collision: encode source key
                        st_key = kname.replace("features:", "").replace(":", "_")
                        features[f"coinank_staleness_ms_{st_key}"] = str(st_ms)
                except Exception:
                    pass

                for fk, fv in rec.items():
                    if not isinstance(fk, str) or not fk.startswith("coinank_"):
                        continue
                    try:
                        val = float(fv) if fv is not None else 0.0
                    except Exception:
                        continue
                    features[fk] = str(val)
        except Exception:
            pass

        # ------------------------------------------------------------------
        # CoinAPI WSDS Depth Features (real-time orderbook microstructure)
        # ingest/live_coinapi_wsds.py writes `msnap:coinapi_wsds:{symbol}` hashes
        # These provide high-quality spoof detection, depth imbalance, and
        # fast-move scores that complement Binance orderbook data.
        # ------------------------------------------------------------------
        try:
            wsds_key = f"msnap:coinapi_wsds:{symbol}"
            wsds_data = self.redis.hgetall(wsds_key)
            if wsds_data and isinstance(wsds_data, dict):
                # Staleness check - only use fresh data
                wsds_staleness = self._safe_float(wsds_data.get("src_staleness_ms", 99999))
                features["depth_staleness_ms"] = str(int(wsds_staleness))
                
                # Mark as stale if > 5 seconds (orderbook data must be fresh)
                wsds_is_stale = 1 if wsds_staleness > 5000 else 0
                features["depth_is_stale"] = str(wsds_is_stale)
                
                # Core depth features (all prefixed with 'depth_' for clarity)
                depth_fields = [
                    # Price data
                    ("mid_px", "depth_mid_price"),
                    ("microprice", "depth_microprice"),
                    ("spread", "depth_spread"),
                    ("best_bid_px", "depth_best_bid"),
                    ("best_ask_px", "depth_best_ask"),
                    ("best_bid_sz", "depth_best_bid_size"),
                    ("best_ask_sz", "depth_best_ask_size"),
                    
                    # Depth aggregates (5-level)
                    ("book_bid_sum_5", "depth_bid_sum_5"),
                    ("book_ask_sum_5", "depth_ask_sum_5"),
                    ("imbalance_5", "depth_imbalance_5"),

                    # Depth totals (bps windows)
                    ("depth_bps_10_bid_usd", "depth_bps_10_bid_usd"),
                    ("depth_bps_10_ask_usd", "depth_bps_10_ask_usd"),
                    ("depth_bps_10_total_usd", "depth_bps_10_total_usd"),
                    ("depth_bps_25_bid_usd", "depth_bps_25_bid_usd"),
                    ("depth_bps_25_ask_usd", "depth_bps_25_ask_usd"),
                    ("depth_bps_25_total_usd", "depth_bps_25_total_usd"),
                    
                    # Microstructure signals (high-value for trading)
                    ("spoof_score", "depth_spoof_score"),
                    ("spoof_score_v1", "depth_spoof_score_v1"),
                    ("spoof_score_v2", "depth_spoof_score_v2"),
                    ("p_false_move", "depth_p_false_move"),
                    ("fast_move_score", "depth_fast_move_score"),
                    ("fast_move_max_1m", "depth_fast_move_1m"),
                    ("fast_move_max_5m", "depth_fast_move_5m"),
                    ("fast_move_max_15m", "depth_fast_move_15m"),
                    ("churn_score", "depth_churn_score"),
                    ("snapback_score", "depth_snapback_score"),

                    # Real-time trade flow (directional pressure)
                    ("trade_buy_notional_1s", "depth_trade_buy_1s"),
                    ("trade_sell_notional_1s", "depth_trade_sell_1s"),
                    ("trade_total_notional_1s", "depth_trade_total_1s"),
                    ("trade_imbalance_1s", "depth_trade_imbalance_1s"),
                    ("trade_buy_notional_5s", "depth_trade_buy_5s"),
                    ("trade_sell_notional_5s", "depth_trade_sell_5s"),
                    ("trade_total_notional_5s", "depth_trade_total_5s"),
                    ("trade_imbalance_5s", "depth_trade_imbalance_5s"),
                    ("impact_bps_1s", "depth_impact_bps_1s"),
                    ("impact_per_musd_1s", "depth_impact_per_musd_1s"),

                    # Quality metrics
                    ("src_quality_score", "depth_quality_score"),
                ]
                
                for src_key, dest_key in depth_fields:
                    val = wsds_data.get(src_key)
                    if val is not None:
                        try:
                            features[dest_key] = str(self._safe_float(val))
                        except Exception:
                            pass
                
                # Add source tracking
                features["depth_source"] = str(wsds_data.get("source", "coinapi_wsds"))
                features["depth_exchange"] = str(wsds_data.get("exchange_id", "BINANCEFTS"))

                # Canonical depth alias for DQ gates
                depth_candidates = [
                    wsds_data.get("depth_bps_25_total_usd"),
                    wsds_data.get("depth_bps_10_total_usd"),
                ]
                depth_total = None
                for dv in depth_candidates:
                    try:
                        if dv is not None:
                            depth_total = float(dv)
                            break
                    except Exception:
                        continue
                if depth_total is None:
                    try:
                        bid_25 = self._safe_float(wsds_data.get("depth_bps_25_bid_usd"), 0.0)
                        ask_25 = self._safe_float(wsds_data.get("depth_bps_25_ask_usd"), 0.0)
                        if (bid_25 + ask_25) > 0:
                            depth_total = float(bid_25 + ask_25)
                    except Exception:
                        depth_total = None
                if depth_total is not None:
                    features["orderbook_depth_usd"] = str(depth_total)
                    features["depth_total_usd"] = str(depth_total)
                    features["depth_usd"] = str(depth_total)
        except Exception:
            pass

        # ------------------------------------------------------------------
        # Binance aggTrades Tape Data (real-time executed trade flow)
        # ingest/live_binance.py writes `msnap:binance_tape:{symbol}` hashes
        # This is the CRITICAL complement to depth/orderbook data.
        # When depth says "buy" but tape says "sell", that's a spoof signal.
        # ------------------------------------------------------------------
        tape_imbalance_5s = None
        tape_imbalance_30s = None
        try:
            tape_key = f"msnap:binance_tape:{symbol}"
            tape_data = self.redis.hgetall(tape_key)
            if tape_data and isinstance(tape_data, dict):
                # Check freshness (must be < 10 seconds old)
                tape_ts = self._safe_float(tape_data.get("ts_ms", 0))
                tape_age_ms = int(time.time() * 1000) - tape_ts if tape_ts else 99999
                features["tape_staleness_ms"] = str(int(tape_age_ms))
                tape_is_stale = 1 if tape_age_ms > 10000 else 0
                features["tape_is_stale"] = str(tape_is_stale)

                if not tape_is_stale:
                    tape_fields = [
                        ("tape_buy_1s",        "tape_buy_notional_1s"),
                        ("tape_sell_1s",       "tape_sell_notional_1s"),
                        ("tape_total_1s",      "tape_total_notional_1s"),
                        ("tape_imbalance_1s",  "tape_imbalance_1s"),
                        ("tape_count_1s",      "tape_count_1s"),
                        ("tape_buy_5s",        "tape_buy_notional_5s"),
                        ("tape_sell_5s",       "tape_sell_notional_5s"),
                        ("tape_total_5s",      "tape_total_notional_5s"),
                        ("tape_imbalance_5s",  "tape_imbalance_5s"),
                        ("tape_count_5s",      "tape_count_5s"),
                        ("tape_buy_30s",       "tape_buy_notional_30s"),
                        ("tape_sell_30s",      "tape_sell_notional_30s"),
                        ("tape_total_30s",     "tape_total_notional_30s"),
                        ("tape_imbalance_30s", "tape_imbalance_30s"),
                        ("tape_count_30s",     "tape_count_30s"),
                        ("tape_cvd",           "tape_cvd"),
                    ]
                    for src_key, dest_key in tape_fields:
                        val = tape_data.get(src_key)
                        if val is not None:
                            try:
                                features[dest_key] = str(self._safe_float(val))
                            except Exception:
                                pass

                    tape_imbalance_5s = self._safe_float(tape_data.get("tape_imbalance_5s"), None)
                    tape_imbalance_30s = self._safe_float(tape_data.get("tape_imbalance_30s"), None)
                    features["tape_source"] = "binance_aggtrades"
        except Exception:
            pass

        # ------------------------------------------------------------------
        # Kline Taker Buy Ratio (from Binance kline V/Q/n fields)
        # ingest/live_binance.py writes these in the market:{symbol}:{tf} bar
        # Provides per-candle directional volume decomposition.
        # ------------------------------------------------------------------
        try:
            mkt_key = f"market:{symbol}:{tf}"
            mkt_raw = self.redis.get(mkt_key)
            if mkt_raw:
                import json as _json
                mkt_bar = _json.loads(mkt_raw) if isinstance(mkt_raw, (str, bytes)) else {}
                tbr = mkt_bar.get("taker_buy_ratio")
                if tbr is not None:
                    features["kline_taker_buy_ratio"] = str(round(float(tbr), 6))
                    features["kline_taker_sell_ratio"] = str(round(1.0 - float(tbr), 6))
                tbbv = mkt_bar.get("taker_buy_base_vol")
                if tbbv is not None:
                    features["kline_taker_buy_base_vol"] = str(float(tbbv))
                tbqv = mkt_bar.get("taker_buy_quote_vol")
                if tbqv is not None:
                    features["kline_taker_buy_quote_vol"] = str(float(tbqv))
                nt = mkt_bar.get("num_trades")
                if nt is not None:
                    features["kline_num_trades"] = str(int(nt))
        except Exception:
            pass

        # ------------------------------------------------------------------
        # Depth-vs-Tape Divergence Score (THE spoof detection signal)
        #
        # When orderbook depth shows buy pressure (depth_imbalance > 0) but
        # actual executed trades show selling (tape_imbalance < 0), that's
        # a classic spoof. This score captures that divergence.
        #
        # Range: 0.0 (depth and tape agree) to 1.0 (extreme divergence)
        # ------------------------------------------------------------------
        try:
            depth_imb_5 = self._safe_float(features.get("depth_imbalance_5"), None)
            dvt_divergence = 0.0
            dvt_components = 0

            # Component 1: 5-second tape vs depth divergence
            if tape_imbalance_5s is not None and depth_imb_5 is not None:
                # Divergence = when they have opposite signs
                # depth_imb_5: positive = more bids (buy depth), negative = more asks
                # tape_imb_5s: positive = taker buying, negative = taker selling
                # Spoof: positive depth imb + negative tape imb (or vice versa)
                sign_disagree = (depth_imb_5 * tape_imbalance_5s) < 0
                raw_div = abs(depth_imb_5 - tape_imbalance_5s) / 2.0  # 0-1 range
                dvt_5s = raw_div * (1.5 if sign_disagree else 0.5)  # boost if opposite signs
                dvt_divergence += min(dvt_5s, 1.0) * 0.5  # 50% weight
                dvt_components += 1

            # Component 2: 30-second tape vs depth divergence (smoother)
            if tape_imbalance_30s is not None and depth_imb_5 is not None:
                sign_disagree_30 = (depth_imb_5 * tape_imbalance_30s) < 0
                raw_div_30 = abs(depth_imb_5 - tape_imbalance_30s) / 2.0
                dvt_30s = raw_div_30 * (1.5 if sign_disagree_30 else 0.5)
                dvt_divergence += min(dvt_30s, 1.0) * 0.3  # 30% weight
                dvt_components += 1

            # Component 3: Existing spoof_score amplification when tape confirms
            existing_spoof = self._safe_float(features.get("depth_spoof_score"), 0.0)
            if existing_spoof > 0.1 and tape_imbalance_5s is not None:
                # If spoof_score is elevated AND tape confirms selling, amplify
                dvt_divergence += min(existing_spoof, 1.0) * 0.2  # 20% weight
                dvt_components += 1

            if dvt_components > 0:
                dvt_divergence = min(dvt_divergence, 1.0)
                features["depth_vs_tape_divergence"] = str(round(dvt_divergence, 6))
                features["depth_vs_tape_components"] = str(dvt_components)
            else:
                features["depth_vs_tape_divergence"] = "0.0"
                features["depth_vs_tape_components"] = "0"
        except Exception:
            features["depth_vs_tape_divergence"] = "0.0"

        # Canonical volatility_pct (legacy DQ requirement)
        try:
            vol_raw = None
            if f"ccxt_volatility_{tf}" in features:
                vol_raw = self._safe_float(features.get(f"ccxt_volatility_{tf}"), None)
            if vol_raw is None:
                vol_raw = self._safe_float(features.get("volatility"), None)
            if vol_raw is not None:
                vol_pct = float(vol_raw) * 100.0 if float(vol_raw) <= 1.0 else float(vol_raw)
                features["volatility"] = str(vol_raw)
                features["volatility_pct"] = str(vol_pct)
        except Exception:
            pass

        # ------------------------------------------------------------------
        # Cross-TF Context: inject key signals from other timeframes.
        # A 5m model can see 15m/1h/4h trends forming, giving early detection
        # of larger moves. Lower TFs give granular momentum info to higher TFs.
        # ------------------------------------------------------------------
        if ENABLE_CROSS_TF_FEATURES and CROSS_TF_SIGNAL_FIELDS:
            try:
                _ALL_TFS = ["1m", "5m", "15m", "1h", "4h"]
                _tf_idx = _ALL_TFS.index(tf) if tf in _ALL_TFS else -1
                _other_tfs = [t for i, t in enumerate(_ALL_TFS) if i != _tf_idx] if _tf_idx >= 0 else []

                for ctx_tf in _other_tfs:
                    ctx_key = f"unified_features:{symbol}:{ctx_tf}"
                    ctx_data = self.redis.hgetall(ctx_key)
                    if not ctx_data:
                        continue
                    # Staleness of the cross-TF source
                    try:
                        ctx_ts = int(float(ctx_data.get("ts_ms", "0")))
                        if ctx_ts > 0:
                            features[f"xtf_{ctx_tf}_age_ms"] = str(max(0, int(time.time() * 1000) - ctx_ts))
                    except Exception:
                        pass

                    for src_field in CROSS_TF_SIGNAL_FIELDS:
                        # TA fields have TF suffix; try both with and without
                        candidates = [src_field]
                        if not src_field.startswith("ind_ta_"):
                            candidates.append(f"ind_ta_{src_field}_{ctx_tf}")
                        else:
                            base = src_field.rsplit("_", 1)[0]
                            candidates.append(f"{base}_{ctx_tf}")

                        val = None
                        for cand in candidates:
                            raw = ctx_data.get(cand)
                            if raw is not None:
                                try:
                                    val = float(raw)
                                    break
                                except (ValueError, TypeError):
                                    continue
                        if val is not None:
                            dest_key = f"xtf_{ctx_tf}_{src_field}"
                            features[dest_key] = str(val)

                    # Higher-TF RSI is extremely high-signal for early detection
                    for rsi_period in ("14", "21"):
                        rsi_val = ctx_data.get(f"ind_ta_RSI_{rsi_period}_{ctx_tf}")
                        if rsi_val is not None:
                            try:
                                features[f"xtf_{ctx_tf}_rsi_{rsi_period}"] = str(float(rsi_val))
                            except (ValueError, TypeError):
                                pass
                    # Higher-TF MACD histogram
                    macd_h = ctx_data.get(f"ind_ta_MACDhist_12_26_9_{ctx_tf}")
                    if macd_h is not None:
                        try:
                            features[f"xtf_{ctx_tf}_macd_hist"] = str(float(macd_h))
                        except (ValueError, TypeError):
                            pass
                    # Higher-TF ATR (volatility regime context)
                    atr_val = ctx_data.get(f"ind_ta_ATR_14_{ctx_tf}")
                    if atr_val is not None:
                        try:
                            features[f"xtf_{ctx_tf}_atr_14"] = str(float(atr_val))
                        except (ValueError, TypeError):
                            pass
                    # Higher-TF price change %
                    pchg = ctx_data.get(f"ccxt_price_change_{ctx_tf}_pct")
                    if pchg is not None:
                        try:
                            features[f"xtf_{ctx_tf}_price_change_pct"] = str(float(pchg))
                        except (ValueError, TypeError):
                            pass
            except Exception:
                pass

        return features

class DualSpeedFeaturePipeline(FeatureAggregator):
    """
    Dual-speed pipeline optimized for low-latency trading:
    - Fast lane: Critical trading data (<30s latency)
    - Slow lane: Context and analysis data (5min latency)
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Use connection pool for better performance
        self.redis_pool = redis.ConnectionPool.from_url(
            REDIS_URL,
            max_connections=50,
            decode_responses=True
        )
        self.redis = redis.Redis(connection_pool=self.redis_pool)
        
        # Define fast and slow lane configurations
        self.fast_timeframes = ['1m', '5m']  # Trading-critical timeframes (ALL SYMBOLS)
        self.slow_timeframes = ['15m', '1h', '4h']  # Context timeframes

        # Hot-reloadable symbol support (config:symbols:active via utils.symbol_manager)
        self._combo_lock = threading.Lock()
        self.symbols: List[str] = self._get_active_symbols()
        self._symbols_fingerprint = ",".join(self.symbols)
        
        # Fast lane: ALL 10 symbols × 2 TF = 20 combinations (for real-time trading)
        self.fast_lane_combos = [(symbol, tf) for symbol in self.symbols for tf in self.fast_timeframes]
        
        # Slow lane: ALL 10 symbols × 3 TF = 30 combinations (for context)
        self.slow_lane_combos = [(symbol, tf) for symbol in self.symbols for tf in self.slow_timeframes]
        
        # Timing configuration
        self.fast_lane_interval = 10  # 10 seconds for fast lane (optimized with more workers)
        self.slow_lane_interval = 300  # 5 minutes for slow lane
        
        # Thread control
        self.fast_thread = None
        self.slow_thread = None
        self.running = True
        
        # Feature caching for optimization
        self._feature_cache = {}
        self._cache_ttl = {}  # Track when cache entries expire
        
        logger.info("=" * 80)
        logger.info("🚀 DUAL-SPEED FEATURE PIPELINE INITIALIZED")
        logger.info("=" * 80)
        logger.info(f"Fast Lane: {len(self.fast_lane_combos)} combinations (10s refresh with FULL features)")
        logger.info(f"  ALL symbols: {self.symbols}")
        logger.info(f"  Timeframes: {self.fast_timeframes}")
        logger.info(f"  Features: COMPREHENSIVE (TA + CoinAnk + TokenMetrics + OHLCV)")
        logger.info(f"  Workers: 20 parallel threads for speed")
        logger.info(f"Slow Lane: {len(self.slow_lane_combos)} combinations (5min refresh with FULL features)")
        logger.info(f"  ALL symbols: {self.symbols}")
        logger.info(f"  Timeframes: {self.slow_timeframes}")
        logger.info(f"  Features: COMPREHENSIVE (TA + CoinAnk + TokenMetrics + OHLCV)")
        logger.info(f"  Workers: 20 parallel threads")
        logger.info(f"Total: {len(self.fast_lane_combos) + len(self.slow_lane_combos)} combinations")
        logger.info("=" * 80)

    def _get_active_symbols(self) -> List[str]:
        """Return active symbols (Redis hot-reload) with config fallback."""
        syms: Any = None
        try:
            from utils.symbol_manager import get_active_symbols
            syms = get_active_symbols(self.redis)
        except Exception:
            syms = None
        if not syms:
            try:
                from utils.symbol_manager import get_symbols_cached
                syms = get_symbols_cached()
            except Exception:
                syms = None
        if not syms:
            try:
                from config import SYMBOLS as _CFG_SYMBOLS
                syms = _CFG_SYMBOLS
            except Exception:
                syms = SYMBOLS
        out = []
        try:
            for s in list(syms or []):
                if not s:
                    continue
                out.append(str(s).upper().strip())
        except Exception:
            out = []
        out = [s for s in out if s]
        return list(dict.fromkeys(out))

    def _maybe_refresh_symbol_combos(self) -> None:
        """Rebuild lane combos when active symbol set changes."""
        try:
            new_syms = self._get_active_symbols()
            new_fp = ",".join(new_syms)
            if new_fp == getattr(self, "_symbols_fingerprint", ""):
                return
            old_set = set(getattr(self, "symbols", []) or [])
            new_set = set(new_syms or [])
            added = sorted(list(new_set - old_set))
            removed = sorted(list(old_set - new_set))
            self.symbols = list(new_syms or [])
            self._symbols_fingerprint = new_fp
            with self._combo_lock:
                self.fast_lane_combos = [(s, tf) for s in self.symbols for tf in self.fast_timeframes]
                self.slow_lane_combos = [(s, tf) for s in self.symbols for tf in self.slow_timeframes]
            logger.warning(
                "SYMBOLS_HOT_RELOAD | active=%d added=%s removed=%s",
                int(len(self.symbols)),
                ",".join(added) if added else "",
                ",".join(removed) if removed else "",
            )
            try:
                self.redis.set(
                    "features:symbols:active",
                    json.dumps({"symbols": self.symbols, "added": added, "removed": removed, "ts_ms": int(time.time() * 1000)}),
                    ex=300,
                )
            except Exception:
                pass
        except Exception as e:
            logger.debug(f"SYMBOLS_HOT_RELOAD_ERR: {e}")
    
    def aggregate_symbol_tf(self, symbol: str, tf: str) -> Dict[str, Any]:
        """
        Override parent method to ensure raw OHLCV fields are included
        The trainer needs: open, high, low, close, volume (not just derived features)
        """
        # Call parent aggregation to get all comprehensive features
        features = super().aggregate_symbol_tf(symbol, tf)
        
        # Inject raw OHLCV fields for ALL timeframes (critical for trainer)
        if features:
            try:
                # Get market data from Redis - TRY COINAPI FIRST, THEN BINANCE
                ohlcv_source = None
                data = None
                
                # 1. Try CoinAPI V1 OHLCV (primary)
                # Keys use lowercase timeframes: latest:coinapi:ohlcv:BTCUSDT:1m
                coinapi_key = f"latest:coinapi:ohlcv:{symbol}:{tf}"
                coinapi_data = self.redis.hgetall(coinapi_key)
                if coinapi_data and coinapi_data.get('close'):
                    data = coinapi_data
                    ohlcv_source = 'coinapi_v1'
                
                # 2. Fallback to market: key (written by CoinAPI V1 or Binance)
                if not data:
                    market_key = f"market:{symbol}:{tf}"
                    market_data = self.redis.get(market_key)
                    if market_data:
                        data = json.loads(market_data)
                        ohlcv_source = data.get('source', 'binance')
                
                if data and isinstance(data, dict):
                    # Add raw OHLCV fields that trainer expects
                    features['open'] = str(data.get('open', 0.0))
                    features['high'] = str(data.get('high', 0.0))
                    features['low'] = str(data.get('low', 0.0))
                    features['close'] = str(data.get('close', 0.0))
                    features['volume'] = str(data.get('volume', 0.0))
                    features['ohlcv_source'] = ohlcv_source  # Track source for debugging
                    logger.debug(f"✅ {symbol}:{tf} - Added OHLCV: close={features['close']} (source={ohlcv_source})")
                    
                # Inject mark/index/basis if available (latency-critical - BINANCE EXCLUSIVE)
                try:
                    pi_key = f"latest:binance:mark_price:{symbol}"
                    pi_data = self.redis.get(pi_key)
                    if pi_data:
                        parsed_pi = json.loads(pi_data)
                        if isinstance(parsed_pi, dict):
                            if 'mark_price' in parsed_pi:
                                features['mark_price'] = str(parsed_pi.get('mark_price'))
                            if 'index_price' in parsed_pi:
                                features['index_price'] = str(parsed_pi.get('index_price'))
                            if 'basis_pct' in parsed_pi:
                                features['basis_pct'] = str(parsed_pi.get('basis_pct'))
                            if 'last_funding_rate' in parsed_pi:
                                features['funding_rate'] = str(parsed_pi.get('last_funding_rate'))
                except Exception:
                    pass
                
                # ── BTC Correlation Feature Injection ─────────────────────────
                # Compute rolling BTC price correlation and beta for each symbol.
                # Written to unified_features hash so both pipeline and trainer see it.
                try:
                    from rl.btc_correlation import compute_btc_correlation
                    btc_corr_enabled = True
                    try:
                        from config import BTC_CORRELATION_ENABLED, BTC_CORRELATION_WINDOWS, BTC_CORRELATION_CACHE_TTL_SEC
                        btc_corr_enabled = BTC_CORRELATION_ENABLED
                        _bcw = BTC_CORRELATION_WINDOWS
                        _bct = BTC_CORRELATION_CACHE_TTL_SEC
                    except ImportError:
                        _bcw = [20, 60, 120]
                        _bct = 30
                    if btc_corr_enabled:
                        corr_feats = compute_btc_correlation(
                            self.redis, symbol, tf=tf, windows=_bcw, cache_ttl=_bct,
                        )
                        features.update(corr_feats)
                except Exception as _bc_err:
                    logger.debug(f"[BTC_CORR] {symbol}:{tf} error: {_bc_err}")

            except Exception as e:
                logger.warning(f"⚠️ Failed to add OHLCV for {symbol}:{tf}: {e}")
        
        return features
    
    def fetch_all_redis_data_batch(self, symbol: str, tf: str) -> Dict[str, Any]:
        """
        Fetch ALL required Redis data in a SINGLE pipeline operation
        Ultra-optimized with minimal latency
        """
        pipeline = self.redis.pipeline()
        
        keys_map = {}
        
        # Price data (CRITICAL - always fetch)
        keys_map['price'] = f"price:{symbol}"
        pipeline.get(keys_map['price'])
        
        # CoinAPI V1 OHLCV (PRIMARY - lower Binance rate limit usage)
        # Keys use lowercase timeframes: latest:coinapi:ohlcv:BTCUSDT:1m
        keys_map[f'coinapi_ohlcv_{tf}'] = f"latest:coinapi:ohlcv:{symbol}:{tf}"
        pipeline.hgetall(keys_map[f'coinapi_ohlcv_{tf}'])
        
        # Market data for this specific timeframe (fallback - Binance or CoinAPI writes here)
        keys_map[f'market_{tf}'] = f"market:{symbol}:{tf}"
        pipeline.get(keys_map[f'market_{tf}'])
        
        # Order book (trading critical)
        keys_map['orderbook_top'] = f"orderbook:top:{symbol}"
        pipeline.get(keys_map['orderbook_top'])
        
        keys_map['orderbook_depth'] = f"orderbook:depth:{symbol}"
        pipeline.get(keys_map['orderbook_depth'])

        # Binance mark/index/premium (latency-sensitive - BINANCE EXCLUSIVE DATA)
        keys_map['binance_mark'] = f"latest:binance:mark_price:{symbol}"
        pipeline.get(keys_map['binance_mark'])
        keys_map['binance_index'] = f"latest:binance:index_price:{symbol}"
        pipeline.get(keys_map['binance_index'])
        keys_map['binance_premium'] = f"latest:binance:premium_index:{symbol}"
        pipeline.get(keys_map['binance_premium'])
        
        # CoinAnk data (sentiment/funding)
        keys_map['coinank'] = f"coinank:{symbol}"
        pipeline.get(keys_map['coinank'])
        
        # Execute ALL at once
        results = pipeline.execute()
        
        # Map results back
        data = {}
        for i, (name, key) in enumerate(keys_map.items()):
            data[name] = results[i]
        
        return data
    
    def calculate_features_fast(self, symbol: str, tf: str, batch_data: Dict) -> Dict[str, Any]:
        """
        Ultra-fast feature calculation for trading-critical data
        Only calculate essential features, skip expensive computations
        """
        features = {}
        current_ts = int(time.time() * 1000)
        
        try:
            # 1. PRICE FEATURES (Essential)
            price_data = batch_data.get('price')
            if price_data:
                try:
                    parsed = json.loads(price_data)
                    if isinstance(parsed, dict):
                        features['price'] = float(parsed.get('price', 0.0))
                        features['price_change_24h'] = float(parsed.get('change_24h', 0.0))
                    else:
                        features['price'] = float(parsed)
                except:
                    pass
            
            # 2. MARKET DATA (Essential)
            market_data = batch_data.get(f'market_{tf}')
            if market_data:
                try:
                    data = json.loads(market_data)
                    if isinstance(data, dict):
                        features['close'] = float(data.get('close', 0.0))
                        features['open'] = float(data.get('open', 0.0))
                        features['high'] = float(data.get('high', 0.0))
                        features['low'] = float(data.get('low', 0.0))
                        features['volume'] = float(data.get('volume', 0.0))
                        
                        # Quick calculations
                        if features['open'] > 0:
                            features['price_change_pct'] = (features['close'] - features['open']) / features['open']
                        if features['close'] > 0:
                            features['volatility'] = (features['high'] - features['low']) / features['close']
                except:
                    pass
            
            # 3. ORDER BOOK (Trading signal)
            ob_data = batch_data.get('orderbook_top')
            if ob_data:
                try:
                    parsed = json.loads(ob_data)
                    if isinstance(parsed, dict) and 'bids' in parsed and 'asks' in parsed:
                        if len(parsed['bids']) > 0:
                            features['best_bid'] = float(parsed['bids'][0][0])
                            features['best_bid_size'] = float(parsed['bids'][0][1])
                        if len(parsed['asks']) > 0:
                            features['best_ask'] = float(parsed['asks'][0][0])
                            features['best_ask_size'] = float(parsed['asks'][0][1])
                        
                        if 'best_bid' in features and 'best_ask' in features:
                            features['spread'] = features['best_ask'] - features['best_bid']
                            mid = (features['best_ask'] + features['best_bid']) / 2
                            features['spread_pct'] = features['spread'] / mid if mid > 0 else 0.0
                except:
                    pass

            # 3b. Binance mark / index / premium
            mark_payload = batch_data.get('binance_mark') or batch_data.get('binance_premium')
            if mark_payload:
                try:
                    parsed = json.loads(mark_payload)
                    if isinstance(parsed, dict):
                        if parsed.get('mark_price') is not None:
                            features['mark_price'] = float(parsed.get('mark_price', 0.0))
                        if parsed.get('index_price') is not None:
                            features['index_price'] = float(parsed.get('index_price', 0.0))
                        if parsed.get('basis_pct') is not None:
                            features['basis_pct'] = float(parsed.get('basis_pct', 0.0))
                        if parsed.get('last_funding_rate') is not None:
                            # Use as a low-latency funding fallback
                            features['funding_rate'] = float(parsed.get('last_funding_rate', 0.0))
                except:
                    pass
            
            # 4. SENTIMENT (Quick check)
            coinank_data = batch_data.get('coinank')
            if coinank_data:
                try:
                    parsed = json.loads(coinank_data)
                    if isinstance(parsed, dict):
                        features['funding_rate'] = float(parsed.get('funding_rate', 0.0))
                        features['oi_change'] = float(parsed.get('oi_change_24h', 0.0))
                except:
                    pass
            
            features['ts_ms'] = str(current_ts)
            
        except Exception as e:
            logger.warning(f"Error in fast feature calc for {symbol}:{tf}: {e}")
        
        return features
    
    def process_fast_lane_combo(self, args: Tuple[str, str]) -> Tuple[str, str, Dict]:
        """Process one fast lane combination with FULL comprehensive features"""
        symbol, tf = args
        
        try:
            # Use the SAME comprehensive aggregation as slow lane
            # This ensures ALL timeframes get full features (TA, CoinAnk, TokenMetrics, etc.)
            unified_features = self.aggregate_symbol_tf(symbol, tf)
            
            # Write to Redis immediately with error handling
            if unified_features:
                try:
                    unified_key = f"unified_features:{symbol}:{tf}"
                    latest_key = f"{unified_key}:latest"

                    # Write both canonical and :latest hash keys atomically
                    pipe = self.redis.pipeline()
                    pipe.hset(unified_key, mapping=unified_features)
                    pipe.expire(unified_key, 60)  # 1 minute expiry - keep data fresh
                    pipe.hset(latest_key, mapping=unified_features)
                    pipe.expire(latest_key, 60)
                    # Compatibility: publish canonical orderbook depth key for DQ gate
                    try:
                        depth_val = self._safe_float(
                            unified_features.get("orderbook_depth_usd")
                            or unified_features.get("depth_bps_25_total_usd")
                            or unified_features.get("depth_total_usd")
                            or unified_features.get("depth_usd"),
                            None,
                        )
                    except Exception:
                        depth_val = None
                    if depth_val is not None:
                        depth_payload = {
                            "symbol": symbol,
                            "depth_usd": float(depth_val),
                            "orderbook_depth_usd": float(depth_val),
                            "ts_ms": int(unified_features.get("ts_ms") or int(time.time() * 1000)),
                            "source": "feature_pipeline",
                        }
                        pipe.set(f"orderbook:depth:{symbol}", json.dumps(depth_payload))
                        pipe.expire(f"orderbook:depth:{symbol}", 60)
                    # B2: Publish notification for event-driven predictions
                    pipe.publish('features:updated', f'{symbol}:{tf}')
                    pipe.execute()
                except redis.exceptions.ConnectionError as ce:
                    logger.error(f"Redis connection error for {symbol}:{tf}: {ce}")
                    # Try to reconnect
                    time.sleep(0.1)
                except Exception as we:
                    logger.error(f"Redis write error for {symbol}:{tf}: {we}")
            
            return (symbol, tf, unified_features if unified_features else {})
            
        except redis.exceptions.ConnectionError as ce:
            logger.error(f"Redis connection error in fast lane {symbol}:{tf}: {ce}")
            time.sleep(0.5)  # Back off on connection errors
            return (symbol, tf, {})
        except Exception as e:
            logger.error(f"Error processing fast lane {symbol}:{tf}: {e}")
            return (symbol, tf, {})
    
    def process_slow_lane_combo(self, args: Tuple[str, str]) -> Tuple[str, str, Dict]:
        """Process one slow lane combination with full features"""
        symbol, tf = args
        
        try:
            # Use the original comprehensive aggregation with timeout protection
            unified_features = self.aggregate_symbol_tf(symbol, tf)
            
            # Write to Redis immediately (just like fast lane!)
            if unified_features:
                try:
                    unified_key = f"unified_features:{symbol}:{tf}"
                    latest_key = f"{unified_key}:latest"

                    # Write both canonical and :latest hash keys atomically
                    pipe = self.redis.pipeline()
                    pipe.hset(unified_key, mapping=unified_features)
                    # Slow lane runs every ~5 minutes; TTL must exceed the interval or keys will disappear
                    # between cycles (causing missing TF data, especially for newly-added symbols).
                    slow_ttl = max(600, int(getattr(self, "slow_lane_interval", 300) * 2))
                    pipe.expire(unified_key, slow_ttl)
                    pipe.hset(latest_key, mapping=unified_features)
                    pipe.expire(latest_key, slow_ttl)
                    # Compatibility: publish canonical orderbook depth key for DQ gate
                    try:
                        depth_val = self._safe_float(
                            unified_features.get("orderbook_depth_usd")
                            or unified_features.get("depth_bps_25_total_usd")
                            or unified_features.get("depth_total_usd")
                            or unified_features.get("depth_usd"),
                            None,
                        )
                    except Exception:
                        depth_val = None
                    if depth_val is not None:
                        depth_payload = {
                            "symbol": symbol,
                            "depth_usd": float(depth_val),
                            "orderbook_depth_usd": float(depth_val),
                            "ts_ms": int(unified_features.get("ts_ms") or int(time.time() * 1000)),
                            "source": "feature_pipeline",
                        }
                        pipe.set(f"orderbook:depth:{symbol}", json.dumps(depth_payload))
                        pipe.expire(f"orderbook:depth:{symbol}", slow_ttl)
                    # B2: Publish notification for event-driven predictions
                    pipe.publish('features:updated', f'{symbol}:{tf}')
                    pipe.execute()
                except redis.exceptions.ConnectionError as ce:
                    logger.error(f"Redis connection error for {symbol}:{tf}: {ce}")
                    time.sleep(0.1)
                except Exception as we:
                    logger.error(f"Redis write error for {symbol}:{tf}: {we}")
            
            return (symbol, tf, unified_features if unified_features else {})
            
        except redis.exceptions.ConnectionError as ce:
            logger.error(f"Redis connection error in slow lane {symbol}:{tf}: {ce}")
            time.sleep(1.0)  # Back off on connection errors
            return (symbol, tf, {})
        except Exception as e:
            logger.error(f"Error processing slow lane {symbol}:{tf}: {e}")
            return (symbol, tf, {})
    
    def run_fast_lane(self):
        """Fast lane processing loop - runs every 10 seconds with FULL features"""
        logger.info("🔥 Fast Lane thread started")
        
        last_run = 0
        consecutive_errors = 0
        MAX_CONSECUTIVE_ERRORS = 50  # INCREASED: More tolerant of transient issues (was 10)
        cycle_count = 0
        
        while self.running:
            try:
                current_time = time.time()
                
                if current_time - last_run >= self.fast_lane_interval:
                    cycle_count += 1
                    start = time.time()

                    # Hot-reload symbols (best-effort; no restart required).
                    try:
                        self._maybe_refresh_symbol_combos()
                    except Exception:
                        pass

                    # Update heartbeat at start of cycle
                    try:
                        self.redis.set('features:fast_lane:last_run_ms', int(time.time() * 1000))
                    except Exception:
                        pass
                    
                    # Process fast lane in parallel with MORE WORKERS for speed
                    try:
                        with self._combo_lock:
                            combos = list(self.fast_lane_combos)
                        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                            # Use submit() instead of map() to avoid timeout issues
                            futures = [executor.submit(self.process_fast_lane_combo, combo) for combo in combos]
                            results = []
                            # INCREASED TIMEOUT: 25 seconds to handle comprehensive feature fetching (was 9s)
                            for future in concurrent.futures.as_completed(futures, timeout=25):
                                try:
                                    results.append(future.result())
                                except Exception as e:
                                    logger.warning(f"❌ Fast lane task failed: {e}")
                                    results.append((None, None, None))
                        
                        success_count = sum(1 for _, _, features in results if features)
                        duration = time.time() - start
                        logger.info(f"⚡ Fast lane updated: {success_count}/{len(combos)} in {duration:.2f}s")
                        consecutive_errors = 0  # Reset error counter on success
                        if success_count > 0:
                            try:
                                self.redis.set('features:fast_lane:last_success_ms', int(time.time() * 1000))
                            except Exception:
                                pass
                        
                    except concurrent.futures.TimeoutError:
                        # WARNING instead of ERROR - timeout is expected under heavy load
                        logger.warning("⚠️  Fast lane timeout - some tasks didn't complete in 25s (continuing)")
                        consecutive_errors += 1
                    except Exception as e:
                        logger.error(f"❌ Fast lane processing error: {e}", exc_info=True)
                        consecutive_errors += 1
                    
                    # Check if too many consecutive errors
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        logger.critical(f"❌ Fast lane failed {MAX_CONSECUTIVE_ERRORS} times in a row! Exiting...")
                        self.running = False
                        break
                    
                    # Update last_run AFTER processing completes
                    last_run = time.time()
                
                time.sleep(1)  # Check every second
                
            except Exception as e:
                logger.error(f"❌ Fast lane thread error: {e}", exc_info=True)
                consecutive_errors += 1
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    logger.critical("❌ Fast lane thread critically failing! Exiting...")
                    self.running = False
                    break
                time.sleep(5)  # Back off on errors
        
        logger.info(f"🛑 Fast lane thread stopped after {cycle_count} cycles")
    
    def run_slow_lane(self):
        """Slow lane processing loop - runs every 5 minutes"""
        logger.info("🐌 Slow Lane thread started")
        
        last_run = 0
        consecutive_errors = 0
        MAX_CONSECUTIVE_ERRORS = 10
        cycle_count = 0
        
        while self.running:
            try:
                current_time = time.time()
                time_since_last_run = current_time - last_run
                
                # Log the wait status every 60 seconds
                if int(time_since_last_run) % 60 == 0 and time_since_last_run > 0:
                    logger.info(f"🐌 Slow lane: Waiting... ({int(time_since_last_run)}s / {self.slow_lane_interval}s)")
                
                if time_since_last_run >= self.slow_lane_interval:
                    cycle_count += 1
                    start = time.time()
                    
                    # Update heartbeat at start of cycle
                    try:
                        self.redis.set('features:slow_lane:last_run_ms', int(time.time() * 1000))
                    except Exception as e:
                        logger.warning(f"⚠️  Failed to update slow_lane:last_run heartbeat: {e}")

                    # Hot-reload symbols (best-effort; no restart required).
                    try:
                        self._maybe_refresh_symbol_combos()
                    except Exception:
                        pass
                    with self._combo_lock:
                        combos = list(self.slow_lane_combos)
                    
                    logger.info(f"📊 Slow Lane CYCLE #{cycle_count}: Processing {len(combos)} combinations...")
                    
                    # Process slow lane in parallel with MORE WORKERS
                    try:
                        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                            # Submit all tasks to executor for parallel processing
                            futures = [executor.submit(self.process_slow_lane_combo, combo) for combo in combos]
                            
                            # Collect results as they complete
                            results = []
                            for future in concurrent.futures.as_completed(futures, timeout=self.slow_lane_interval - 10):
                                try:
                                    result = future.result(timeout=10)
                                    results.append(result)
                                except Exception as e:
                                    logger.warning(f"❌ Failed to process slow lane task: {e}")
                                    results.append((None, None, None))
                        
                        success_count = sum(1 for _, _, features in results if features)
                        duration = time.time() - start
                        logger.info(f"📊 Slow lane CYCLE #{cycle_count} COMPLETE: {success_count}/{len(combos)} in {duration:.2f}s")
                        consecutive_errors = 0  # Reset error counter on success
                        
                        # Update success heartbeat
                        try:
                            self.redis.set('features:slow_lane:last_success_ms', int(time.time() * 1000))
                        except Exception as e:
                            logger.warning(f"⚠️  Failed to update slow_lane:last_success heartbeat: {e}")
                        
                    except Exception as e:
                        logger.error(f"❌ Slow lane processing error in cycle #{cycle_count}: {e}", exc_info=True)
                        consecutive_errors += 1
                    
                    # Check if too many consecutive errors
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        logger.critical(f"❌ Slow lane failed {MAX_CONSECUTIVE_ERRORS} times in a row! Exiting...")
                        self.running = False
                        break
                    
                    # Update last_run AFTER processing completes
                    last_run = time.time()
                    logger.info(f"📊 Slow lane: Next cycle in {self.slow_lane_interval}s")
                
                time.sleep(5)  # Check every 5 seconds
                
            except Exception as e:
                logger.error(f"❌ Slow lane thread error: {e}", exc_info=True)
                consecutive_errors += 1
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    logger.critical("❌ Slow lane thread critically failing! Exiting...")
                    self.running = False
                    break
                time.sleep(10)  # Back off on errors
        
        logger.info(f"🛑 Slow lane thread stopped after {cycle_count} cycles")
    
    def start(self):
        """Start both fast and slow lane threads"""
        logger.info("=" * 80)
        logger.info("🚀 STARTING DUAL-SPEED FEATURE PIPELINE")
        logger.info("=" * 80)
        
        self.running = True
        
        # Update main heartbeat (JSON format for compatibility with health_probe)
        heartbeat_data = json.dumps({
            "timestamp_ms": int(time.time() * 1000),
            "status": "starting"
        })
        self.redis.set("heartbeat:FeaturePipeline", heartbeat_data)
        
        # Start fast lane thread
        self.fast_thread = threading.Thread(target=self.run_fast_lane, daemon=True)
        self.fast_thread.start()
        
        # Start slow lane thread
        self.slow_thread = threading.Thread(target=self.run_slow_lane, daemon=True)
        self.slow_thread.start()
        
        logger.info("✅ Both lanes started successfully")
        logger.info("=" * 80)
        
        # Keep main thread alive and monitor
        status_counter = 0
        last_health_check = time.time()
        
        try:
            while self.running:
                # Update main heartbeat every 5 seconds (JSON format)
                try:
                    heartbeat_data = json.dumps({
                        "timestamp_ms": int(time.time() * 1000),
                        "status": "running"
                    })
                    self.redis.set("heartbeat:FeaturePipeline", heartbeat_data)
                except redis.exceptions.ConnectionError as ce:
                    logger.error(f"❌ Redis connection error in heartbeat: {ce}")
                    time.sleep(2)
                
                time.sleep(5)
                
                # Print status every minute (12 × 5s = 60s)
                status_counter += 1
                if status_counter >= 12:
                    logger.info("━" * 80)
                    logger.info("📊 SYSTEM STATUS:")
                    logger.info(f"   ✅ Fast Lane: {'Active' if self.fast_thread.is_alive() else '❌ DEAD'} (updates every {self.fast_lane_interval}s)")
                    logger.info(f"   ✅ Slow Lane: {'Active' if self.slow_thread.is_alive() else '❌ DEAD'} (updates every {self.slow_lane_interval//60}min)")
                    logger.info(f"   💓 Main heartbeat: Updated")
                    logger.info("━" * 80)
                    status_counter = 0
                
                # Check thread health every 30 seconds
                current_time = time.time()
                if current_time - last_health_check >= 30:
                    if not self.fast_thread.is_alive():
                        logger.error("❌ Fast lane thread died! Restarting...")
                        self.fast_thread = threading.Thread(target=self.run_fast_lane, daemon=True)
                        self.fast_thread.start()
                    
                    if not self.slow_thread.is_alive():
                        logger.error("❌ Slow lane thread died! Restarting...")
                        self.slow_thread = threading.Thread(target=self.run_slow_lane, daemon=True)
                        self.slow_thread.start()
                    
                    last_health_check = current_time
                
        except KeyboardInterrupt:
            logger.info("\n🛑 Shutdown requested by user")
        except Exception as e:
            logger.error(f"❌ Main loop error: {e}", exc_info=True)
        finally:
            # Cleanup
            logger.info("🛑 Shutting down pipeline...")
            self.running = False
            
            # Wait for threads to finish
            if self.fast_thread and self.fast_thread.is_alive():
                logger.info("  Waiting for fast lane to stop...")
                self.fast_thread.join(timeout=10)
            
            if self.slow_thread and self.slow_thread.is_alive():
                logger.info("  Waiting for slow lane to stop...")
                self.slow_thread.join(timeout=10)
            
            # Close Redis connection pool
            try:
                self.redis_pool.disconnect()
                logger.info("  ✅ Redis connections closed")
            except Exception as e:
                logger.warning(f"  Warning: Error closing Redis pool: {e}")
            
            logger.info("✅ Pipeline shutdown complete")

def main():
    """Main entry point with proper error handling"""
    logger.info("=" * 80)
    logger.info("🚀 ULTRA-LOW-LATENCY DUAL-SPEED FEATURE PIPELINE v2.0")
    logger.info("=" * 80)
    logger.info("Architecture:")
    logger.info("  ⚡ Fast Lane: Trading-critical data (<30s latency)")
    logger.info("     - ALL 10 symbols × 2 timeframes (1m, 5m)")
    logger.info("     - Updates every 15 seconds")
    logger.info("  📊 Slow Lane: Context & analysis (5min latency)")
    logger.info("     - ALL 10 symbols × 3 timeframes (15m, 1h, 4h)")
    logger.info("     - Updates every 5 minutes")
    logger.info("=" * 80)
    
    try:
        pipeline = DualSpeedFeaturePipeline(update_interval=5)
        pipeline.start()
    except KeyboardInterrupt:
        logger.info("🛑 User interrupted")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)
        return 1
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
