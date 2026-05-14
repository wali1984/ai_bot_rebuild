"""
Market Regime Detection System
Comprehensive regime analysis using Coinank + TokenMetrics data
Detects: Bull, Bear, Sideways, Volatile, Calm regimes with confidence scores
"""

import json
import time
import logging
import numpy as np
from typing import Dict, Any, Optional, List, Tuple
from collections import deque
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RegimeState:
    """Market regime state with confidence"""
    regime: str  # 'bull', 'bear', 'sideways', 'volatile', 'calm'
    confidence: float  # 0.0 to 1.0
    trend_strength: float  # -1.0 (strong bear) to +1.0 (strong bull)
    volatility_score: float  # 0.0 (calm) to 1.0 (extreme)
    sentiment_score: float  # -1.0 (fear) to +1.0 (greed)
    liquidity_score: float  # 0.0 (dry) to 1.0 (liquid)
    momentum_score: float  # -1.0 (bearish) to +1.0 (bullish)
    timestamp: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'regime': self.regime,
            'confidence': self.confidence,
            'trend_strength': self.trend_strength,
            'volatility_score': self.volatility_score,
            'sentiment_score': self.sentiment_score,
            'liquidity_score': self.liquidity_score,
            'momentum_score': self.momentum_score,
            'timestamp': self.timestamp
        }


class MarketRegimeDetector:
    """
    Comprehensive market regime detection using:
    - Coinank: OI, funding, liquidations, long/short ratios
    - TokenMetrics: AI grades, sentiment, predictions
    - Price action: Volatility, momentum, trend
    """
    
    def __init__(self, redis_client, lookback_periods: int = 24):
        """
        Initialize regime detector
        
        Args:
            redis_client: Redis connection
            lookback_periods: Number of periods to analyze (default: 24 hours)
        """
        self.redis = redis_client
        self.lookback_periods = lookback_periods
        
        # Cache recent regime states
        self.regime_history = deque(maxlen=100)
        self.last_regime_check = 0
        self.cache_ttl = 300  # 5 minutes
        
        # Regime thresholds (tunable)
        self.thresholds = {
            'bull': {
                'trend_strength': 0.3,      # Positive momentum
                'sentiment': 0.2,            # Positive sentiment
                'funding': 0.0005,           # Positive funding (longs pay shorts)
                'oi_growth': 0.05            # 5% OI growth
            },
            'bear': {
                'trend_strength': -0.3,     # Negative momentum
                'sentiment': -0.2,           # Negative sentiment
                'funding': -0.0005,          # Negative funding (shorts pay longs)
                'oi_growth': -0.05           # 5% OI decline
            },
            'sideways': {
                'trend_strength': 0.15,      # Low momentum (abs)
                'volatility': 0.3            # Low volatility
            },
            'volatile': {
                'volatility': 0.6,           # High volatility
                'liquidation_ratio': 0.01    # 1% liquidation vs OI
            }
        }
        
        logger.info(f"🔍 Market Regime Detector initialized: {lookback_periods}h lookback")
    
    def detect_regime(self, symbol: str = 'BTCUSDT') -> RegimeState:
        """
        Detect current market regime using all available data sources
        
        Returns:
            RegimeState with regime classification and confidence
        """
        try:
            # Check cache
            current_time = time.time()
            if current_time - self.last_regime_check < self.cache_ttl:
                cached = self.redis.get(f'market_regime:{symbol}')
                if cached:
                    data = json.loads(cached)
                    return RegimeState(**data)
            
            # === STEP 1: Gather Coinank Data ===
            coinank_data = self._get_coinank_signals(symbol)
            
            # === STEP 2: Gather TokenMetrics Data ===
            tm_data = self._get_tokenmetrics_signals(symbol)
            
            # === STEP 3: Gather Price Action Data ===
            price_data = self._get_price_action(symbol)
            
            # === STEP 4: Calculate Component Scores ===
            trend_score = self._calculate_trend_score(coinank_data, tm_data, price_data)
            volatility_score = self._calculate_volatility_score(coinank_data, price_data)
            sentiment_score = self._calculate_sentiment_score(coinank_data, tm_data)
            liquidity_score = self._calculate_liquidity_score(coinank_data)
            momentum_score = self._calculate_momentum_score(coinank_data, tm_data, price_data)
            
            # === STEP 5: Classify Regime ===
            regime, confidence = self._classify_regime(
                trend_score, volatility_score, sentiment_score, 
                liquidity_score, momentum_score
            )
            
            # Create regime state
            state = RegimeState(
                regime=regime,
                confidence=confidence,
                trend_strength=trend_score,
                volatility_score=volatility_score,
                sentiment_score=sentiment_score,
                liquidity_score=liquidity_score,
                momentum_score=momentum_score,
                timestamp=current_time
            )
            
            # Cache result
            self.redis.setex(
                f'market_regime:{symbol}',
                self.cache_ttl,
                json.dumps(state.to_dict())
            )
            
            # Store in history
            self.regime_history.append(state)
            self.last_regime_check = current_time
            
            logger.info(
                f"🔍 Regime detected for {symbol}: {regime.upper()} "
                f"(conf={confidence:.2f}, trend={trend_score:+.2f}, "
                f"vol={volatility_score:.2f}, sentiment={sentiment_score:+.2f})"
            )
            
            return state
            
        except Exception as e:
            logger.error(f"❌ Regime detection failed for {symbol}: {e}")
            # Return neutral regime on error
            return RegimeState(
                regime='sideways',
                confidence=0.5,
                trend_strength=0.0,
                volatility_score=0.5,
                sentiment_score=0.0,
                liquidity_score=0.5,
                momentum_score=0.0,
                timestamp=time.time()
            )
    
    def _get_coinank_signals(self, symbol: str) -> Dict[str, Any]:
        """Get CoinAnk signals using our current Redis key contracts.

        Preferred:
        - `trading.coinank_signal_adapter` (reads `unified_features:{symbol}:{tf}` and `features:global_coinank:*`)

        Fallback:
        - Endpoint JSON payloads written by `ingest/live_coinank.py` under
          `features:coinank_endpoint:{endpoint}:{symbol}:{exchange}:{interval}:latest`
        """
        try:
            # Fast path: unified_features-based adapter (freshness-aware)
            try:
                from trading.coinank_signal_adapter import get_coinank_adapter
                adapter = get_coinank_adapter(self.redis)
                ss = adapter.get_symbol_signals(symbol, tf="1h")
                gs = adapter.get_global_signals()
                if ss.ok:
                    # Map to the regime detector's expected signal names
                    if "oi_total" in ss.signals:
                        signals = {"oi_total": float(ss.signals["oi_total"])}
                    else:
                        signals = {}
                    if "oi_change" in ss.signals:
                        signals["oi_24h_change"] = float(ss.signals["oi_change"])
                    if "funding_rate" in ss.signals:
                        # regime uses avg/std; we only have current here, but it is still useful
                        signals["funding_rate_avg"] = float(ss.signals["funding_rate"])
                    if "long_short_ratio" in ss.signals:
                        signals["ls_ratio_avg"] = float(ss.signals["long_short_ratio"])
                    if "liq_total_usd" in ss.signals:
                        signals["liquidation_24h"] = float(ss.signals["liq_total_usd"])
                        oi_total = float(signals.get("oi_total") or 0.0)
                        signals["liquidation_intensity"] = float(signals["liquidation_24h"] / oi_total) if oi_total > 0 else 0.0

                    # Global context from CoinAnk global aggregator (if fresh)
                    try:
                        gsig = (gs or {}).get("signals") or {}
                        if isinstance(gsig, dict) and gsig:
                            # These improve regime classification without requiring TokenMetrics
                            if "btc_dominance" in gsig:
                                signals["btc_dominance"] = float(gsig["btc_dominance"]) / 100.0
                            if "fear_greed" in gsig:
                                fg = float(gsig["fear_greed"])
                                signals["fear_greed"] = (fg - 50.0) / 50.0
                            if "market_sentiment" in gsig:
                                signals["market_sentiment"] = float(gsig["market_sentiment"])
                            if "volatility_index" in gsig:
                                signals["global_volatility_index"] = float(gsig["volatility_index"])
                    except Exception:
                        pass

                    # If we got anything meaningful, return it.
                    if signals:
                        return signals
            except Exception:
                pass

            signals: Dict[str, Any] = {}
            exchange = "Binance"
            lookback = max(2, int(getattr(self, "lookback_periods", 24) or 24))

            def _loads(raw):
                if raw is None:
                    return None
                raw = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
                if not raw:
                    return None
                try:
                    return json.loads(raw)
                except Exception:
                    return None

            def _get_ep(endpoint: str, sym: str, interval: str) -> Optional[Dict[str, Any]]:
                # Primary (collision-free) endpoint key written by ingest/live_coinank.py
                key = f"features:coinank_endpoint:{endpoint}:{sym}:{exchange}:{interval}:latest"
                raw = self.redis.get(key)
                rec = _loads(raw)
                if isinstance(rec, dict):
                    return rec
                return None

            def _to_ts_ms(x) -> int:
                try:
                    t = int(float(x))
                    # If seconds, convert to ms
                    if 0 < t < 1_000_000_000_000:
                        t *= 1000
                    return t
                except Exception:
                    return 0

            def _extract_series(rec: Optional[Dict[str, Any]], value_keys: Tuple[str, ...]) -> List[Tuple[int, float]]:
                if not isinstance(rec, dict):
                    return []
                raw = rec.get("raw_data")
                if raw is None:
                    raw = rec.get("data")
                # Common CoinAnk schema: {"data":[...]}
                if isinstance(raw, dict) and isinstance(raw.get("data"), list):
                    raw = raw.get("data")
                if not isinstance(raw, list):
                    return []

                out: List[Tuple[int, float]] = []
                for item in raw:
                    ts_ms = 0
                    val = None

                    if isinstance(item, dict):
                        # Timestamp candidates
                        for tkey in ("ts", "tss", "timestamp", "time", "begin"):
                            if tkey in item:
                                ts_ms = _to_ts_ms(item.get(tkey))
                                break
                        # Value candidates
                        for vkey in value_keys:
                            if vkey in item:
                                val = item.get(vkey)
                                break
                    elif isinstance(item, (list, tuple)):
                        # Common schema: [ts, value, ...]
                        if len(item) >= 1:
                            ts_ms = _to_ts_ms(item[0])
                        if len(item) >= 2:
                            val = item[1]

                    try:
                        if val is None:
                            continue
                        out.append((ts_ms, float(val)))
                    except Exception:
                        continue

                # If timestamps are missing, keep insertion order
                if out and all(t == 0 for t, _ in out):
                    return [(i, v) for i, (_, v) in enumerate(out)]
                return out

            # ------------------------------------------------------------------
            # Open Interest (OI) - prefer symbol chart (USD value); fallback to OI kline open/close delta.
            # ------------------------------------------------------------------
            oi_rec = _get_ep("openInterest_symbol_Chart", symbol, "1h")
            oi_series = _extract_series(oi_rec, ("coinValue", "coinValueUsd", "sumOpenInterestUsd", "openInterest", "oi", "value"))
            if oi_series:
                oi_series.sort(key=lambda tv: tv[0])
                vals = [v for _, v in oi_series if v is not None]
                if vals:
                    signals["oi_total"] = float(vals[-1])
                    window = vals[-min(len(vals), lookback):]
                    if len(window) >= 2:
                        first = float(window[0])
                        last = float(window[-1])
                        signals["oi_24h_change"] = (last - first) / first if first > 0 else 0.0
                        m = float(np.mean(window)) if window else 0.0
                        signals["oi_volatility"] = float(np.std(window) / m) if m > 0 else 0.0
            else:
                # Fallback: compute OI change from kline open/close
                oi_k = _get_ep("openInterest_kline", symbol, "1h")
                # Usually open/close are in the record's flattened fields; use those if present.
                try:
                    oi_open = float((oi_k or {}).get("coinank_openInterest_kline_data_0_open", 0) or 0)
                    oi_close = float((oi_k or {}).get("coinank_openInterest_kline_data_0_close", 0) or 0)
                    if oi_open > 0 and oi_close > 0:
                        signals["oi_total"] = oi_close
                        signals["oi_24h_change"] = (oi_close - oi_open) / oi_open
                except Exception:
                    pass

            # ------------------------------------------------------------------
            # Funding rate (1h kline preferred; indicator fallback)
            # ------------------------------------------------------------------
            fr_rec = _get_ep("fundingRate_kline", symbol, "1h")
            fr_series = _extract_series(fr_rec, ("fundingRate", "rate", "close", "fr"))
            if not fr_series:
                fr_rec = _get_ep("fundingRate_indicator", symbol, "1h")
                fr_series = _extract_series(fr_rec, ("fundingRate", "rate", "fr", "close"))
            if fr_series:
                fr_series.sort(key=lambda tv: tv[0])
                vals = [v for _, v in fr_series]
                window = vals[-min(len(vals), lookback):]
                signals["funding_rate_avg"] = float(np.mean(window)) if window else 0.0
                signals["funding_rate_std"] = float(np.std(window)) if len(window) > 1 else 0.0

            # ------------------------------------------------------------------
            # Liquidations (24h-ish via 1h liquidation_history turnover)
            # ------------------------------------------------------------------
            liq_rec = _get_ep("liquidation_history", symbol, "1h")
            if isinstance(liq_rec, dict):
                raw = liq_rec.get("raw_data")
                if isinstance(raw, dict) and isinstance(raw.get("data"), list):
                    raw = raw.get("data")
                if isinstance(raw, list) and raw:
                    # Sort by ts if present
                    def _ts(item):
                        if isinstance(item, dict):
                            return _to_ts_ms(item.get("ts") or item.get("timestamp") or item.get("tss") or 0)
                        if isinstance(item, (list, tuple)) and item:
                            return _to_ts_ms(item[0])
                        return 0
                    raw_sorted = sorted(raw, key=_ts)
                    recent = raw_sorted[-min(len(raw_sorted), lookback):]
                    long_liq = 0.0
                    short_liq = 0.0
                    for it in recent:
                        if isinstance(it, dict):
                            # Prefer USD turnover fields if present
                            lv = it.get("longTurnover", it.get("longLiquidationUsd", it.get("longAmount", 0)))
                            sv = it.get("shortTurnover", it.get("shortLiquidationUsd", it.get("shortAmount", 0)))
                        elif isinstance(it, (list, tuple)):
                            # Unknown schema; skip
                            continue
                        else:
                            continue
                        try:
                            long_liq += float(lv or 0)
                        except Exception:
                            pass
                        try:
                            short_liq += float(sv or 0)
                        except Exception:
                            pass

                    total_liq = float(long_liq + short_liq)
                    signals["liquidation_24h"] = total_liq
                    signals["liquidation_long_short_ratio"] = (long_liq / short_liq) if short_liq > 0 else 1.0
                    oi_total = float(signals.get("oi_total") or 0.0)
                    signals["liquidation_intensity"] = (total_liq / oi_total) if oi_total > 0 else 0.0

            # ------------------------------------------------------------------
            # Long/Short ratios (global accounts, 1h)
            # ------------------------------------------------------------------
            ls_rec = _get_ep("ls_global_account_ratio", symbol, "1h")
            ls_series = _extract_series(ls_rec, ("longShortRatio", "lsr", "ratio"))
            if ls_series:
                ls_series.sort(key=lambda tv: tv[0])
                vals = [v for _, v in ls_series if v is not None]
                window = vals[-min(len(vals), lookback):]
                if window:
                    signals["ls_ratio_avg"] = float(np.mean(window))
                    if len(window) >= 2 and window[0] != 0:
                        signals["ls_ratio_trend"] = (float(window[-1]) - float(window[0])) / float(window[0])

            # ------------------------------------------------------------------
            # CVD (15m) - use 24h window (96 points)
            # ------------------------------------------------------------------
            cvd_rec = _get_ep("marketOrder_getAggCvd", symbol, "15m")
            cvd_series = _extract_series(cvd_rec, ("cvd", "value", "delta"))
            if cvd_series:
                cvd_series.sort(key=lambda tv: tv[0])
                vals = [v for _, v in cvd_series]
                window = vals[-min(len(vals), 96):]
                if len(window) >= 2:
                    signals["cvd_24h_change"] = float(window[-1]) - float(window[0])
                    signals["cvd_momentum"] = float(np.gradient(window[-12:]).mean()) if len(window) >= 12 else 0.0

            return signals

        except Exception as e:
            logger.warning(f"⚠️ CoinAnk signals fetch failed: {e}")
            return {}
    
    def _get_tokenmetrics_signals(self, symbol: str) -> Dict[str, Any]:
        """Get TokenMetrics data: AI grades, sentiment, predictions"""
        try:
            signals = {}
            
            # === TM Grades (A-F rating) ===
            tm_grade_key = f"features:tokenmetrics:{symbol}:latest"
            # Check key type first to avoid WRONGTYPE error
            key_type = self.redis.type(tm_grade_key)
            tm_data = None
            
            if key_type == 'hash':
                tm_data = self.redis.hgetall(tm_grade_key)
            elif key_type == 'string':
                tm_json = self.redis.get(tm_grade_key)
                if tm_json:
                    try:
                        tm_data = json.loads(tm_json)
                    except:
                        pass
            
            if tm_data:
                # Extract numeric grades (convert A=5, B=4, C=3, D=2, F=1)
                grade_map = {'A': 5, 'B': 4, 'C': 3, 'D': 2, 'F': 1}
                
                tm_grade = tm_data.get('tm_grade', 'C')
                tech_grade = tm_data.get('tech_grade', 'C')
                fund_grade = tm_data.get('fund_grade', 'C')
                
                signals['tm_grade_score'] = grade_map.get(tm_grade, 3) / 5.0  # Normalize to 0-1
                signals['tech_grade_score'] = grade_map.get(tech_grade, 3) / 5.0
                signals['fund_grade_score'] = grade_map.get(fund_grade, 3) / 5.0
                signals['composite_grade'] = (signals['tm_grade_score'] + signals['tech_grade_score'] + signals['fund_grade_score']) / 3
            
            # === Trading Signals ===
            trading_signal_key = f"tokenmetrics:trading_signals:{symbol}:latest"
            ts_data = self.redis.get(trading_signal_key)
            if ts_data:
                ts = json.loads(ts_data).get('data', {})
                if isinstance(ts, list) and ts:
                    ts = ts[0]
                
                # Signal direction: 1=buy, 0=hold, -1=sell
                signal = ts.get('signal', 'hold').lower()
                signal_map = {'buy': 1.0, 'strong_buy': 1.5, 'hold': 0.0, 'sell': -1.0, 'strong_sell': -1.5}
                signals['trading_signal'] = signal_map.get(signal, 0.0)
                signals['signal_confidence'] = float(ts.get('confidence', 0.5))
            
            # === Price Prediction ===
            pred_key = f"tokenmetrics:price_prediction:{symbol}:latest"
            pred_data = self.redis.get(pred_key)
            if pred_data:
                pred = json.loads(pred_data).get('data', {})
                if isinstance(pred, list) and pred:
                    pred = pred[0]
                
                current_price = float(pred.get('current_price', 0))
                short_term_pred = float(pred.get('short_term_prediction', current_price))
                medium_term_pred = float(pred.get('medium_term_prediction', current_price))
                
                if current_price > 0:
                    signals['short_term_return'] = (short_term_pred - current_price) / current_price
                    signals['medium_term_return'] = (medium_term_pred - current_price) / current_price
            
            # === AI Reports (Global Sentiment) ===
            ai_report_key = "tokenmetrics:ai_reports:global:latest"
            report_data = self.redis.get(ai_report_key)
            if report_data:
                report = json.loads(report_data).get('data', {})
                if isinstance(report, list) and report:
                    report = report[0]
                
                # Extract sentiment from report text (simple keyword matching)
                report_text = report.get('summary', '').lower()
                bullish_words = ['bullish', 'uptrend', 'rally', 'surge', 'gain', 'positive']
                bearish_words = ['bearish', 'downtrend', 'decline', 'drop', 'fall', 'negative']
                
                bullish_count = sum(word in report_text for word in bullish_words)
                bearish_count = sum(word in report_text for word in bearish_words)
                
                if bullish_count + bearish_count > 0:
                    signals['ai_sentiment'] = (bullish_count - bearish_count) / (bullish_count + bearish_count)
                else:
                    signals['ai_sentiment'] = 0.0
            
            # === Market Metrics (Fear & Greed) ===
            market_metrics_key = "tokenmetrics:market_metrics:global:latest"
            mm_data = self.redis.get(market_metrics_key)
            if mm_data:
                mm = json.loads(mm_data).get('data', {})
                if isinstance(mm, list) and mm:
                    mm = mm[0]
                
                # Fear/greed index (0-100, normalize to -1 to +1)
                fear_greed = float(mm.get('fear_greed_index', 50))
                signals['fear_greed'] = (fear_greed - 50) / 50  # -1 (fear) to +1 (greed)
                
                # BTC dominance (indicates altseason vs BTC season)
                btc_dominance = float(mm.get('btc_dominance', 50))
                signals['btc_dominance'] = btc_dominance / 100
            
            return signals
            
        except Exception as e:
            logger.warning(f"⚠️ TokenMetrics signals fetch failed: {e}")
            return {}
    
    def _get_price_action(self, symbol: str) -> Dict[str, Any]:
        """Get price action data from Redis (OHLCV)"""
        try:
            signals = {}
            
            # Get recent price data from unified features or Binance cache
            price_key = f"unified_features:{symbol}:1h"
            price_data = self.redis.hgetall(price_key)
            
            if price_data:
                # Extract price metrics
                close_price = float(price_data.get('close', 0))
                high_24h = float(price_data.get('high_24h', close_price))
                low_24h = float(price_data.get('low_24h', close_price))
                volume_24h = float(price_data.get('volume_24h', 0))
                
                if close_price > 0 and high_24h > low_24h:
                    signals['price_range_24h'] = (high_24h - low_24h) / close_price
                    signals['price_position_24h'] = (close_price - low_24h) / (high_24h - low_24h) if high_24h > low_24h else 0.5
                
                # Volatility (ATR-like)
                signals['volatility_24h'] = signals.get('price_range_24h', 0.02)
                
                # Volume analysis
                signals['volume_24h'] = volume_24h
            
            return signals
            
        except Exception as e:
            logger.warning(f"⚠️ Price action fetch failed: {e}")
            return {}
    
    def _calculate_trend_score(self, coinank: Dict, tm: Dict, price: Dict) -> float:
        """Calculate overall trend strength (-1 to +1)"""
        scores = []
        
        # OI growth (expanding OI = trend strength)
        if 'oi_24h_change' in coinank:
            scores.append(np.clip(coinank['oi_24h_change'] * 5, -1, 1))  # Scale to -1,1
        
        # TokenMetrics composite grade
        if 'composite_grade' in tm:
            scores.append((tm['composite_grade'] - 0.5) * 2)  # Convert 0-1 to -1,1
        
        # Price prediction
        if 'short_term_return' in tm:
            scores.append(np.clip(tm['short_term_return'] * 10, -1, 1))
        
        # CVD momentum
        if 'cvd_momentum' in coinank:
            scores.append(np.clip(coinank['cvd_momentum'] / 1e6, -1, 1))  # Normalize CVD
        
        return np.mean(scores) if scores else 0.0
    
    def _calculate_volatility_score(self, coinank: Dict, price: Dict) -> float:
        """Calculate volatility score (0 to 1)"""
        scores = []
        
        # Price range
        if 'price_range_24h' in price:
            scores.append(np.clip(price['price_range_24h'] * 10, 0, 1))  # 10% = max
        
        # OI volatility
        if 'oi_volatility' in coinank:
            scores.append(np.clip(coinank['oi_volatility'] * 5, 0, 1))
        
        # Liquidation intensity
        if 'liquidation_intensity' in coinank:
            scores.append(np.clip(coinank['liquidation_intensity'] * 100, 0, 1))
        
        # Funding rate volatility
        if 'funding_rate_std' in coinank:
            scores.append(np.clip(coinank['funding_rate_std'] * 1000, 0, 1))
        
        return np.mean(scores) if scores else 0.5
    
    def _calculate_sentiment_score(self, coinank: Dict, tm: Dict) -> float:
        """Calculate market sentiment (-1 to +1)"""
        scores = []
        
        # Long/Short ratio
        if 'ls_ratio_avg' in coinank:
            # > 1 = more longs = bullish, < 1 = more shorts = bearish
            ls_ratio = coinank['ls_ratio_avg']
            scores.append(np.clip((ls_ratio - 1.0) * 2, -1, 1))
        
        # Liquidation ratio (more long liq = bearish)
        if 'liquidation_long_short_ratio' in coinank:
            liq_ratio = coinank['liquidation_long_short_ratio']
            scores.append(np.clip((1 / liq_ratio - 1.0) if liq_ratio > 0 else 0, -1, 1))
        
        # TokenMetrics trading signal
        if 'trading_signal' in tm:
            scores.append(np.clip(tm['trading_signal'], -1, 1))
        
        # AI sentiment
        if 'ai_sentiment' in tm:
            scores.append(tm['ai_sentiment'])
        
        # Fear & Greed
        if 'fear_greed' in tm:
            scores.append(tm['fear_greed'])
        
        return np.mean(scores) if scores else 0.0
    
    def _calculate_liquidity_score(self, coinank: Dict) -> float:
        """Calculate market liquidity (0 to 1)"""
        scores = []
        
        # Total OI (higher = more liquid)
        if 'oi_total' in coinank:
            # Normalize to 0-1 (assume $10B as max)
            scores.append(np.clip(coinank['oi_total'] / 10e9, 0, 1))
        
        # Liquidation intensity (lower = more liquid/stable)
        if 'liquidation_intensity' in coinank:
            scores.append(1.0 - np.clip(coinank['liquidation_intensity'] * 100, 0, 1))
        
        return np.mean(scores) if scores else 0.5
    
    def _calculate_momentum_score(self, coinank: Dict, tm: Dict, price: Dict) -> float:
        """Calculate momentum score (-1 to +1)"""
        scores = []
        
        # CVD change (cumulative buying/selling pressure)
        if 'cvd_24h_change' in coinank:
            scores.append(np.clip(coinank['cvd_24h_change'] / 1e8, -1, 1))  # Normalize
        
        # L/S ratio trend
        if 'ls_ratio_trend' in coinank:
            scores.append(np.clip(coinank['ls_ratio_trend'], -1, 1))
        
        # Funding rate (positive = bullish momentum)
        if 'funding_rate_avg' in coinank:
            scores.append(np.clip(coinank['funding_rate_avg'] * 1000, -1, 1))
        
        # Price position in 24h range
        if 'price_position_24h' in price:
            scores.append((price['price_position_24h'] - 0.5) * 2)  # Convert to -1,1
        
        return np.mean(scores) if scores else 0.0
    
    def _classify_regime(self, trend: float, volatility: float, sentiment: float,
                        liquidity: float, momentum: float) -> Tuple[str, float]:
        """
        Classify regime based on component scores
        
        Returns:
            (regime_name, confidence)
        """
        # Calculate regime probabilities
        probs = {}
        
        # Bull: Strong positive trend + positive sentiment + positive momentum
        bull_score = (
            max(0, trend) * 0.35 +
            max(0, sentiment) * 0.25 +
            max(0, momentum) * 0.25 +
            (1 - volatility) * 0.15  # Prefer stable bull markets
        )
        probs['bull'] = bull_score
        
        # Bear: Strong negative trend + negative sentiment + negative momentum
        bear_score = (
            max(0, -trend) * 0.35 +
            max(0, -sentiment) * 0.25 +
            max(0, -momentum) * 0.25 +
            (1 - volatility) * 0.15  # Prefer stable bear markets
        )
        probs['bear'] = bear_score
        
        # Sideways: Low trend + low volatility
        sideways_score = (
            (1 - abs(trend)) * 0.4 +
            (1 - volatility) * 0.4 +
            (1 - abs(momentum)) * 0.2
        )
        probs['sideways'] = sideways_score
        
        # Volatile: High volatility regardless of direction
        volatile_score = (
            volatility * 0.6 +
            abs(momentum) * 0.2 +
            (1 - liquidity) * 0.2  # Low liquidity increases volatility
        )
        probs['volatile'] = volatile_score
        
        # Calm: Low volatility + high liquidity + neutral sentiment
        calm_score = (
            (1 - volatility) * 0.5 +
            liquidity * 0.3 +
            (1 - abs(sentiment)) * 0.2
        )
        probs['calm'] = calm_score
        
        # Select regime with highest probability
        regime = max(probs, key=probs.get)
        confidence = probs[regime]
        
        # Normalize confidence to 0-1 range
        confidence = np.clip(confidence, 0, 1)
        
        return regime, confidence
    
    def get_regime_params(self, regime: str) -> Dict[str, Any]:
        """Get trading parameter adjustments for regime"""
        params = {
            'bull': {
                'position_size_multiplier': 1.3,    # Larger positions
                'leverage_multiplier': 1.2,         # Higher leverage
                'confidence_threshold': 0.65,       # Lower threshold
                'min_trading_confidence': 0.60,     # More aggressive
                'stop_loss_multiplier': 1.2,        # Wider stops
                'take_profit_multiplier': 1.5,      # Larger targets
                'preferred_side': 'LONG'
            },
            'bear': {
                'position_size_multiplier': 0.8,    # Smaller positions
                'leverage_multiplier': 0.8,         # Lower leverage
                'confidence_threshold': 0.75,       # Higher threshold
                'min_trading_confidence': 0.70,     # More conservative
                'stop_loss_multiplier': 0.8,        # Tighter stops
                'take_profit_multiplier': 1.2,      # Closer targets
                'preferred_side': 'SHORT'
            },
            'sideways': {
                'position_size_multiplier': 0.6,    # Much smaller positions
                'leverage_multiplier': 0.7,         # Lower leverage
                'confidence_threshold': 0.80,       # Much higher threshold
                'min_trading_confidence': 0.75,     # Very conservative
                'stop_loss_multiplier': 0.7,        # Very tight stops
                'take_profit_multiplier': 1.0,      # Quick exits
                'preferred_side': None              # No bias
            },
            'volatile': {
                'position_size_multiplier': 0.5,    # Very small positions
                'leverage_multiplier': 0.6,         # Minimal leverage
                'confidence_threshold': 0.85,       # Very high threshold
                'min_trading_confidence': 0.80,     # Extremely conservative
                'stop_loss_multiplier': 0.6,        # Very tight stops
                'take_profit_multiplier': 0.8,      # Fast exits
                'preferred_side': None
            },
            'calm': {
                'position_size_multiplier': 1.0,    # Normal positions
                'leverage_multiplier': 1.0,         # Normal leverage
                'confidence_threshold': 0.70,       # Standard threshold
                'min_trading_confidence': 0.65,     # Standard
                'stop_loss_multiplier': 1.0,        # Normal stops
                'take_profit_multiplier': 1.3,      # Normal targets
                'preferred_side': None
            }
        }
        
        return params.get(regime, params['calm'])
