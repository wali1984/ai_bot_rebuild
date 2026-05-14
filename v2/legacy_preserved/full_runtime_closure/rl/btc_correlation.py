"""
BTC Correlation Feature Module
==============================
Computes rolling price-return correlation between BTC and each altcoin.
Injected into the feature pipeline and trainer inference features.

Features produced per symbol per timeframe:
  btc_corr_20   — 20-bar rolling Pearson correlation with BTC returns
  btc_corr_60   — 60-bar rolling correlation
  btc_corr_120  — 120-bar rolling correlation
  btc_corr_delta — btc_corr_60 - btc_corr_20 (regime shift detector)
  btc_beta       — rolling beta (cov/var) vs BTC (sensitivity multiplier)

Kill switch: BTC_CORRELATION_ENABLED (config.py, default True)
Cache TTL:   BTC_CORRELATION_CACHE_TTL_SEC (default 30s)
"""

import logging
import time
import json
import math
from typing import Dict, List, Optional, Any

logger = logging.getLogger("btc_correlation")

# Module-level cache to avoid recomputation within the same cycle
_cache: Dict[str, Dict[str, Any]] = {}
_cache_ts: Dict[str, float] = {}


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Convert any value to float safely."""
    if val is None:
        return default
    try:
        v = float(val)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except (ValueError, TypeError):
        return default


def _pearson_correlation(x: List[float], y: List[float]) -> float:
    """Compute Pearson correlation between two lists. Returns 0.0 on error."""
    n = min(len(x), len(y))
    if n < 5:
        return 0.0
    x = x[-n:]
    y = y[-n:]
    
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    
    cov_xy = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n)) / n
    var_x = sum((xi - mean_x) ** 2 for xi in x) / n
    var_y = sum((yi - mean_y) ** 2 for yi in y) / n
    
    denom = math.sqrt(var_x * var_y)
    if denom < 1e-12:
        return 0.0
    
    corr = cov_xy / denom
    return max(-1.0, min(1.0, corr))


def _compute_beta(x_returns: List[float], y_returns: List[float]) -> float:
    """Compute rolling beta = cov(asset, BTC) / var(BTC)."""
    n = min(len(x_returns), len(y_returns))
    if n < 5:
        return 1.0  # Default beta = 1 (moves with BTC)
    x = x_returns[-n:]
    y = y_returns[-n:]
    
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    
    cov_xy = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n)) / n
    var_y = sum((yi - mean_y) ** 2 for yi in y) / n
    
    if var_y < 1e-12:
        return 1.0
    
    beta = cov_xy / var_y
    return max(-5.0, min(5.0, beta))


def _get_price_series(redis_client, symbol: str, tf: str, bars: int = 150) -> List[float]:
    """
    Get recent close prices from Redis OHLCV data.
    
    Primary source: ohlcv:list:binance:{symbol}:{tf}  (Redis list, up to 2000 entries)
    Written by ingest/live_binance.py on every new candle close.
    Each entry is JSON: {"timestamp": ..., "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}
    
    Fallback: ccxt:latest:{symbol}:{tf}  (single latest candle hash, only 1 bar)
    """
    prices = []

    # Strategy 1: Rolling OHLCV list from live_binance.py (primary, up to 2000 bars)
    try:
        list_key = f"ohlcv:list:binance:{symbol}:{tf}"
        # Read last N entries (list is chronologically ordered, newest at the end)
        raw = redis_client.lrange(list_key, -bars, -1)
        if raw and len(raw) >= 10:
            for entry in raw:
                try:
                    d = json.loads(entry) if isinstance(entry, str) else json.loads(entry.decode())
                    v = _safe_float(d.get("close"))
                    if v > 0:
                        prices.append(v)
                except Exception:
                    continue
            if len(prices) >= 10:
                return prices
    except Exception as e:
        logger.debug("[BTC_CORR] ohlcv:list:binance read failed for %s:%s: %s", symbol, tf, e)

    # Strategy 2: Fallback — single latest candle from ccxt:latest hash
    prices.clear()
    try:
        hash_key = f"ccxt:latest:{symbol}:{tf}"
        close_val = redis_client.hget(hash_key, "close")
        if close_val:
            v = _safe_float(close_val)
            if v > 0:
                prices.append(v)
    except Exception:
        pass

    return prices


def _prices_to_returns(prices: List[float]) -> List[float]:
    """Convert price series to log-returns."""
    if len(prices) < 2:
        return []
    returns = []
    for i in range(1, len(prices)):
        if prices[i - 1] > 0 and prices[i] > 0:
            returns.append(math.log(prices[i] / prices[i - 1]))
        else:
            returns.append(0.0)
    return returns


def compute_btc_correlation(
    redis_client,
    symbol: str,
    tf: str = "5m",
    windows: Optional[List[int]] = None,
    cache_ttl: int = 30,
) -> Dict[str, str]:
    """
    Compute BTC correlation features for a given symbol.
    
    Returns dict with string values (ready for Redis hash injection):
        btc_corr_20, btc_corr_60, btc_corr_120, btc_corr_delta, btc_beta
    
    For BTCUSDT itself, returns perfect correlation (1.0) and beta (1.0).
    """
    if windows is None:
        windows = [20, 60, 120]
    
    # BTCUSDT correlates perfectly with itself
    if symbol.upper() in ("BTCUSDT", "BTCUSD"):
        result = {"btc_beta": "1.0", "btc_corr_delta": "0.0"}
        for w in windows:
            result[f"btc_corr_{w}"] = "1.0"
        return result
    
    # Check cache
    cache_key = f"{symbol}:{tf}"
    now = time.time()
    if cache_key in _cache and (now - _cache_ts.get(cache_key, 0)) < cache_ttl:
        return _cache[cache_key]
    
    # Default result (neutral correlation)
    result = {"btc_beta": "1.0", "btc_corr_delta": "0.0"}
    for w in windows:
        result[f"btc_corr_{w}"] = "0.0"
    
    try:
        max_bars = max(windows) + 10
        
        # Get BTC prices
        btc_prices = _get_price_series(redis_client, "BTCUSDT", tf, bars=max_bars)
        if len(btc_prices) < 15:
            logger.debug("[BTC_CORR] Insufficient BTC price data (%d bars) for %s:%s", len(btc_prices), symbol, tf)
            _cache[cache_key] = result
            _cache_ts[cache_key] = now
            return result
        
        # Get altcoin prices
        alt_prices = _get_price_series(redis_client, symbol, tf, bars=max_bars)
        if len(alt_prices) < 15:
            logger.debug("[BTC_CORR] Insufficient %s price data (%d bars) for %s:%s", symbol, len(alt_prices), symbol, tf)
            _cache[cache_key] = result
            _cache_ts[cache_key] = now
            return result
        
        # Convert to returns
        btc_returns = _prices_to_returns(btc_prices)
        alt_returns = _prices_to_returns(alt_prices)
        
        # Compute rolling correlations at each window
        correlations = {}
        for w in windows:
            if len(btc_returns) >= w and len(alt_returns) >= w:
                corr = _pearson_correlation(alt_returns[-w:], btc_returns[-w:])
                correlations[w] = corr
                result[f"btc_corr_{w}"] = f"{corr:.4f}"
            else:
                correlations[w] = 0.0
        
        # Correlation delta (regime shift detector)
        if len(windows) >= 2:
            short_w = min(windows)
            long_w = sorted(windows)[1]  # Second-smallest window
            delta = correlations.get(short_w, 0.0) - correlations.get(long_w, 0.0)
            result["btc_corr_delta"] = f"{delta:.4f}"
        
        # Beta vs BTC (using medium window)
        beta_window = windows[1] if len(windows) >= 2 else windows[0]
        if len(btc_returns) >= beta_window and len(alt_returns) >= beta_window:
            beta = _compute_beta(alt_returns[-beta_window:], btc_returns[-beta_window:])
            result["btc_beta"] = f"{beta:.4f}"
        
        logger.debug(
            "[BTC_CORR] %s:%s corr_20=%.3f corr_60=%.3f corr_120=%.3f beta=%.3f delta=%.3f",
            symbol, tf,
            correlations.get(20, 0), correlations.get(60, 0), correlations.get(120, 0),
            _safe_float(result.get("btc_beta")), _safe_float(result.get("btc_corr_delta")),
        )
        
    except Exception as e:
        logger.warning("[BTC_CORR] Error computing correlation for %s:%s: %s", symbol, tf, e)
    
    _cache[cache_key] = result
    _cache_ts[cache_key] = now
    return result


def inject_btc_correlation_features(
    decoded_features: Dict[str, str],
    redis_client,
    symbol: str,
    tf: str = "5m",
) -> Dict[str, str]:
    """
    Inject BTC correlation features into a decoded feature dict.
    Called from the trainer's GPU batch feature collection loop.
    
    Safe to call on any symbol — BTCUSDT returns identity correlation.
    Returns the modified decoded_features dict.
    """
    try:
        from config import (
            BTC_CORRELATION_ENABLED,
            BTC_CORRELATION_WINDOWS,
            BTC_CORRELATION_CACHE_TTL_SEC,
        )
    except ImportError:
        BTC_CORRELATION_ENABLED = True
        BTC_CORRELATION_WINDOWS = [20, 60, 120]
        BTC_CORRELATION_CACHE_TTL_SEC = 30
    
    if not BTC_CORRELATION_ENABLED:
        return decoded_features
    
    try:
        corr_features = compute_btc_correlation(
            redis_client,
            symbol,
            tf=tf,
            windows=BTC_CORRELATION_WINDOWS,
            cache_ttl=BTC_CORRELATION_CACHE_TTL_SEC,
        )
        decoded_features.update(corr_features)
    except Exception as e:
        logger.debug("[BTC_CORR_INJECT] Error for %s:%s: %s", symbol, tf, e)
    
    return decoded_features
