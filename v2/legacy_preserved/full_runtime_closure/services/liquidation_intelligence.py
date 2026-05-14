"""
Liquidation Intelligence Layer
F) Implements liquidation zone detection and risk metrics
"""

import time
import json
import logging
from typing import Dict, List, Optional, Tuple
import numpy as np
from collections import defaultdict

import config

logger = logging.getLogger(__name__)


class LiquidationIntelligenceService:
    """F) Liquidation Intelligence Layer - Detects and tracks liquidation zones"""
    
    def __init__(self, redis_client, binance_client=None):
        self.redis = redis_client
        self.binance_client = binance_client
        self.update_interval = 10  # Update every 10 seconds
        self.last_update = 0
        self.liquidation_zones = {}  # {symbol: computed feature snapshot}
        self.last_warn: Dict[str, float] = {}
        
    def update_liquidation_zones(self):
        """F.1) Update liquidation zone detection"""
        current_time = time.time()
        if current_time - self.last_update < self.update_interval:
            return  # Too soon to update
        
        try:
            for symbol in config.SYMBOLS:
                zones = self._compute_features_from_unified(symbol)
                if zones:
                    key = f"liquidation:zones:{symbol}"
                    self.redis.setex(key, 30, json.dumps(zones))
                    self.liquidation_zones[symbol] = zones
            self.last_update = current_time
        except Exception as e:
            logger.debug(f"Liquidation zone update error: {e}")

    def _compute_features_from_unified(self, symbol: str) -> Optional[Dict[str, float]]:
        """Compute liquidation-derived features using unified_features hashes."""
        best = None
        best_ts = -1
        price = 0.0

        for tf in config.TIMEFRAMES:
            key = f"unified_features:{symbol}:{tf}"
            data = self.redis.hgetall(key)
            if not data:
                continue
            try:
                ts = int(data.get("liquidation_updated_ts") or 0)
                if ts <= best_ts:
                    continue
                price_val = float(data.get("close") or data.get("price") or data.get("last_price") or 0.0)
                ll = float(data.get("liquidation_long_level") or 0.0)
                sl = float(data.get("liquidation_short_level") or 0.0)
                lstr = float(data.get("liquidation_long_strength") or 0.0)
                sstr = float(data.get("liquidation_short_strength") or 0.0)
                volume = float(data.get("liquidation_volume") or 0.0)
            except Exception:
                continue

            best_ts = ts
            price = price_val
            best = {
                "long_level": ll,
                "short_level": sl,
                "long_strength": lstr,
                "short_strength": sstr,
                "volume": volume,
                "tf": tf,
                "updated_ts": ts,
            }

        if not best or price <= 0:
            now = time.time()
            last = self.last_warn.get(symbol, 0)
            if now - last > 60:
                logger.warning(f"⚠️ No liquidation features found for {symbol}; expected unified_features hash")
                self.last_warn[symbol] = now
            return None

        eps = 1e-9
        d_long = (price - best["long_level"]) / price if best["long_level"] > 0 else 0.0
        d_short = (best["short_level"] - price) / price if best["short_level"] > 0 else 0.0

        total_strength = best["long_strength"] + best["short_strength"]
        imbalance = (best["short_strength"] - best["long_strength"]) / (total_strength + eps)
        intensity = total_strength / (total_strength + 1e6)

        return {
            'lq_long_cluster_distance': float(d_long),
            'lq_short_cluster_distance': float(d_short),
            'liquidation_intensity': float(intensity),
            'margin_stress_index': float(imbalance),
            'timestamp': int(time.time() * 1000),
            'tf': best["tf"],
        }
    
    def get_liquidation_features(self, symbol: str) -> Dict[str, float]:
        """F.2) Get liquidation features for observation injection"""
        try:
            self.update_liquidation_zones()
            key = f"liquidation:zones:{symbol}"
            zones_data = self.redis.get(key)

            if zones_data:
                zones = json.loads(zones_data) if isinstance(zones_data, str) else zones_data
                return {
                    'lq_long_cluster_distance': zones.get('lq_long_cluster_distance', 0.0),
                    'lq_short_cluster_distance': zones.get('lq_short_cluster_distance', 0.0),
                    'lq_intensity': zones.get('liquidation_intensity', 0.0),
                    'lq_margin_stress': zones.get('margin_stress_index', 0.0)
                }
            else:
                return {
                    'lq_long_cluster_distance': 0.0,
                    'lq_short_cluster_distance': 0.0,
                    'lq_intensity': 0.0,
                    'lq_margin_stress': 0.0
                }

        except Exception as e:
            logger.debug(f"Error getting liquidation features: {e}")
            return {
                'lq_long_cluster_distance': 0.0,
                'lq_short_cluster_distance': 0.0,
                'lq_intensity': 0.0,
                'lq_margin_stress': 0.0
            }

    def compute_liquidation_price(
        self,
        side: str,
        entry_price: float,
        quantity: float,
        wallet_balance: float,
        mmr: float,
        maint_amount: float = 0.0,
    ) -> float:
        """
        Approximate Binance USDⓈ-M liquidation price (cross mode).
        side: 'LONG' or 'SHORT'
        mmr: maintenance margin rate (decimal)
        maint_amount: maintenance margin absolute amount (tier-based)
        """
        if quantity <= 0 or entry_price <= 0 or wallet_balance <= 0:
            return 0.0

        notional = entry_price * quantity
        if side.upper() == "LONG":
            denom = quantity * (1 - mmr)
            if denom <= 0:
                return 0.0
            numer = notional - wallet_balance + maint_amount
            return max(0.0, numer / denom)
        else:
            denom = quantity * (1 + mmr)
            if denom <= 0:
                return 0.0
            numer = notional + wallet_balance - maint_amount
            return max(0.0, numer / denom)





